"""应用装配根（FR-3 / FR-17 / Task 4）。

按 env 构建算法 Deps 与 api 依赖：双引擎、真实 L0 SchemaProvider、PgRepository、QueryRunner、
LLM/Embedding 客户端（无 key 照常构造，调用期抛 LLMUnavailableError → E_LLM_UNAVAILABLE）、
内存 checkpointer、经算法 loader 预加载的 Resources。

懒连接：引擎/Provider 构造不触库（TR-4.3）；触库动作集中在 startup_sequence（FR-17）：
create_all → L0 抽取 →（EMB_* 齐全时）ensure exemplar+hnsw；可选增强失败只降级不退出。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import algorithm
from algorithm.config import Settings as AlgorithmSettings
from algorithm.config import load_settings
from algorithm.llm.client import build_llm_client
from algorithm.llm.embeddings import OpenAICompatibleEmbeddingClient
from algorithm.protocols import Deps
from algorithm.resources.loader import load_resources
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from .config import ApiConfig, load_config
from .data.engines import AnalyticsEngine, build_app_engine
from .data.pg_exemplar_repo import PgExemplarRepository
from .data.query_runner import PgQueryRunner
from .data.schema_provider_pg import PgSchemaProvider
from .storage.ddl import exemplar_ddl, meta_schema_cache_ddl
from .storage.models import Base
from .storage.repositories import MessageRepo, ReportRepo, SessionRepo

logger = logging.getLogger("backend_service.composition")


@dataclass
class AppContext:
    """依赖容器：main 工厂与路由经 app.state.ctx 消费。"""

    config: ApiConfig
    algo_settings: AlgorithmSettings
    deps: Deps
    checkpointer: Any
    chain_runner: Callable[..., Any]  # 唯一 run_chain 引用（离线测试注入同签名替身）
    session_repo: SessionRepo
    message_repo: MessageRepo
    report_repo: ReportRepo
    app_engine: Any
    analytics: AnalyticsEngine
    schema_provider: PgSchemaProvider
    repository: Optional[PgExemplarRepository]
    probes: dict[str, Callable[[], str]] = field(default_factory=dict)  # {"db","llm","embedding"}
    # lifespan 钩子（build_context 注入；离线测试注入的替身 context 缺省即跳过生命周期）
    startup: Optional[Callable[[], None]] = None
    shutdown: Optional[Callable[[], None]] = None

    # 懒建的服务（避免 composition ↔ application 循环依赖）
    _conversation: Any = field(default=None, init=False, repr=False)
    _reports: Any = field(default=None, init=False, repr=False)

    @property
    def conversation(self):
        if self._conversation is None:
            from .application.conversation_service import ConversationService

            self._conversation = ConversationService(
                config=self.config,
                chain_runner=self.chain_runner,
                deps=self.deps,
                checkpointer=self.checkpointer,
                session_repo=self.session_repo,
                message_repo=self.message_repo,
            )
        return self._conversation

    @property
    def reports(self):
        if self._reports is None:
            from .application.report_service import ReportService

            self._reports = ReportService(
                config=self.config,
                chain_runner=self.chain_runner,
                deps=self.deps,
                report_repo=self.report_repo,
                message_repo=self.message_repo,
                session_repo=self.session_repo,
            )
        return self._reports


def build_context(config: Optional[ApiConfig] = None, *, env: Optional[dict] = None, chain_runner: Any = None) -> AppContext:
    """按 env 装配；DB 可懒连接、无 key/无 EMB 可构建（TR-4.3）。"""
    config = config or load_config(env)
    algo_settings = load_settings(env)
    app_engine = build_app_engine(config.app_database_url, schema=config.app_schema)
    analytics = AnalyticsEngine(
        config.analytics_database_url,
        schema=config.dw_schema,
        statement_timeout_ms=config.query_timeout_seconds * 1000,
    )
    schema_provider = PgSchemaProvider(analytics, schema=config.dw_schema)
    query_runner = PgQueryRunner(analytics, row_limit_max=config.row_limit_max)
    llm = build_llm_client(algo_settings)
    embedding = OpenAICompatibleEmbeddingClient(algo_settings) if algo_settings.emb_configured else None
    repository = (
        PgExemplarRepository(app_engine, schema=config.app_schema, emb_dim=algo_settings.emb_dim)
        if algo_settings.emb_configured
        else None
    )
    resources = load_resources(algo_settings.resources_path)
    deps = Deps(
        settings=algo_settings,
        llm=llm,
        schema_provider=schema_provider,
        query_runner=query_runner,
        embedding=embedding,
        repository=repository,
        resources=resources,
    )
    session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    ctx = AppContext(
        config=config,
        algo_settings=algo_settings,
        deps=deps,
        checkpointer=_new_checkpointer(),
        chain_runner=chain_runner or algorithm.run_chain,
        session_repo=SessionRepo(session_factory),
        message_repo=MessageRepo(session_factory),
        report_repo=ReportRepo(session_factory),
        app_engine=app_engine,
        analytics=analytics,
        schema_provider=schema_provider,
        repository=repository,
    )
    ctx.probes = {"db": _db_probe(app_engine), "llm": _llm_probe(algo_settings), "embedding": _emb_probe(algo_settings)}
    ctx.startup = lambda: startup_sequence(ctx)
    ctx.shutdown = lambda: dispose_context(ctx)
    return ctx


def _new_checkpointer() -> Any:
    """进程内内存 checkpointer（NFR-4 单进程假设）。"""
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


# ---- 健康探针（FR-16；失败不拖死请求） ----
def _db_probe(app_engine) -> Callable[[], str]:
    def probe() -> str:
        with app_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"

    return probe


def _llm_probe(settings: AlgorithmSettings) -> Callable[[], str]:
    if not settings.llm_configured:
        return lambda: "unconfigured"

    def probe() -> str:
        import openai

        client = openai.OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key, timeout=3.0, max_retries=0)
        client.models.list()
        return "ok"

    return probe


def _emb_probe(settings: AlgorithmSettings) -> Callable[[], str]:
    if not settings.emb_configured:
        return lambda: "unconfigured"

    def probe() -> str:
        import openai

        client = openai.OpenAI(base_url=settings.emb_base_url, api_key=settings.emb_api_key, timeout=3.0, max_retries=0)
        client.models.list()
        return "ok"

    return probe


# ---- 启动序列（FR-17 / Task 10） ----
def startup_sequence(ctx: AppContext) -> None:
    """create_all（幂等）→ L0 抽取 →（EMB 齐全）ensure exemplar+hnsw。

    db 失败 → 抛异常启动失败；可选增强（exemplar/meta 缓存）失败 → 告警降级不退出。
    """
    # 0. app schema 兜底（init SQL 建好时为 no-op；无权限时忽略，后续 create_all 会给出真实错误）
    try:
        with ctx.app_engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {ctx.config.app_schema}"))
    except Exception as e:  # noqa: BLE001
        logger.warning("app schema 预建跳过（%s）", e)

    # 1. create_all 幂等建表（NFR-5）
    Base.metadata.create_all(ctx.app_engine)

    # 2. L0 抽取并进程内缓存（必需；dw 不可达视为 db 失败 → 启动失败）
    ctx.schema_provider.refresh()

    # 3. 可选增强：EMB_* 齐全才 ensure exemplar 表与 hnsw（FR-21/AC-16）
    if ctx.algo_settings.emb_configured and ctx.repository is not None:
        try:
            _ensure_exemplar(ctx)
            # meta_schema_cache 落表（开关控制，§4.1）
            if ctx.config.meta_schema_cache_enabled:
                _ensure_meta_cache(ctx)
        except Exception as e:  # noqa: BLE001
            logger.warning("exemplar/meta_schema_cache 初始化失败，降级为不启用（%s）", e)


def _ensure_exemplar(ctx: AppContext) -> None:
    with ctx.app_engine.begin() as conn:
        for stmt in exemplar_ddl(ctx.config.app_schema, ctx.algo_settings.emb_dim):
            conn.execute(text(stmt))


def _ensure_meta_cache(ctx: AppContext) -> None:
    with ctx.app_engine.begin() as conn:
        for stmt in meta_schema_cache_ddl(ctx.config.app_schema):
            conn.execute(text(stmt))
    assert ctx.repository is not None
    ctx.repository.save_schema_cache(ctx.schema_provider.all_blocks())


def dispose_context(ctx: AppContext) -> None:
    try:
        ctx.app_engine.dispose()
    except Exception:  # noqa: BLE001
        pass
