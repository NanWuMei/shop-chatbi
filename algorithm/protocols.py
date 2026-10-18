"""协议定义（SDD §5/§7）：外部能力全部经协议注入，mock/真实实现可换、链路代码不动。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel

from .config import Settings
from .state import Exemplar, QueryResult, SchemaBlock


class LLMUnavailableError(Exception):
    """LLM 未配置或调用失败（节点内重试 1 次后映射 E_LLM_UNAVAILABLE）。"""


class EmbeddingUnavailableError(Exception):
    """Embedding 未配置或调用失败（S3 据此降级 lexical）。"""


class QueryTimeoutError(Exception):
    """QueryRunner 超时信号。"""


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        *,
        agent: str,
        tier: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> BaseModel:
        """OpenAI 兼容 chat completions + 结构化输出；不合 schema 视同失败。"""
        ...


@runtime_checkable
class EmbeddingClient(Protocol):
    @property
    def available(self) -> bool: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class SchemaProvider(Protocol):
    """L0 库结构来源（启动抽取/静态快照均可）。"""

    def all_blocks(self) -> list[SchemaBlock]: ...

    def enum_candidates(self, term: str) -> list[dict[str, str]]:
        """按词命中枚举/层级候选（如「美妆」多候选），返回 [{value,label,table,column}]。"""
        ...


@runtime_checkable
class QueryRunner(Protocol):
    async def run(self, sql: str) -> QueryResult:
        """算法不直连库；执行只经本协议（超时/行限由后端配）。"""
        ...


@runtime_checkable
class Repository(Protocol):
    """资源读写（§7 切换预留：psycopg+pgvector ↔ Supabase 只换实现）。"""

    async def search_exemplars(
        self,
        *,
        embedding: Optional[list[float]] = None,
        keywords: Optional[list[str]] = None,
        top_k: int = 5,
    ) -> list[Exemplar]: ...

    async def upsert_exemplar(self, exemplar: Exemplar, embedding: Optional[list[float]] = None) -> None: ...

    async def load_schema_cache(self) -> Optional[list[SchemaBlock]]: ...


# 节点事件回调：node_started / node_finished / terminal（不含 HTTP/SSE 语义）
OnEvent = Callable[[str, dict[str, Any]], None]


@dataclass
class Resources:
    """resources/loader.py 加载结果；全部为空即「无增强」。"""

    metrics: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    calendar: dict[str, Any] = field(default_factory=dict)
    templates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Deps:
    """装配入口：后端步注入真实实现，本步注入 mock/静态实现。"""

    settings: Settings
    llm: LLMClient
    schema_provider: SchemaProvider
    query_runner: QueryRunner
    embedding: Optional[EmbeddingClient] = None
    repository: Optional[Repository] = None
    resources: Resources = field(default_factory=Resources)
    on_event: Optional[OnEvent] = None


def deps_from_config(config: Any) -> Deps:
    """从 LangGraph RunnableConfig 取注入的依赖容器。"""
    configurable = (config or {}).get("configurable") or {}
    deps = configurable.get("deps")
    if deps is None:  # pragma: no cover - 装配错误尽早暴露
        raise RuntimeError("缺少 deps：请在 config['configurable']['deps'] 注入依赖容器")
    return deps


def emit(deps: Deps, event: str, payload: dict[str, Any]) -> None:
    """节点事件回调（node_started/node_finished/terminal）；不含 HTTP/SSE 语义。"""
    if deps.on_event is not None:
        deps.on_event(event, payload)
