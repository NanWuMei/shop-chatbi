"""TR-4.3：装配根在无 key/无 EMB 下可构建（DB 懒连接，不触库）。"""
from backend_service.composition import build_context
from algorithm.protocols import Deps


def _build(env_extra: dict | None = None):
    env = dict(env_extra or {})
    return build_context(env=env)


def test_offline_build_no_keys():
    ctx = _build()
    # Deps 齐全、类型正确
    assert isinstance(ctx.deps, Deps)
    assert ctx.deps.query_runner is not None
    assert ctx.deps.schema_provider is not None
    assert ctx.deps.llm is not None
    # EMB 未配置 → 无 embedding/仓储（检索由算法降级）
    assert ctx.deps.embedding is None
    assert ctx.repository is None
    assert ctx.deps.repository is None
    # 探针与生命周期钩子就位（构造即存在，未触库）
    assert set(ctx.probes) == {"db", "llm", "embedding"}
    assert ctx.probes["llm"]() == "unconfigured"
    assert ctx.probes["embedding"]() == "unconfigured"
    assert callable(ctx.startup) and callable(ctx.shutdown)
    # 三个仓储就绪（sessionmaker 懒连接）
    assert ctx.session_repo is not None
    assert ctx.message_repo is not None
    assert ctx.report_repo is not None


def test_offline_build_with_emb_env_constructs_repository():
    """EMB_* 齐全时构建 embedding 与 PgRepository（构造不触库）。"""
    ctx = _build(
        {
            "EMB_BASE_URL": "https://emb.example.com/v1",
            "EMB_API_KEY": "sk-test",
            "EMB_MODEL": "emb-1",
            "EMB_DIM": "1024",
        }
    )
    assert ctx.deps.embedding is not None
    assert ctx.repository is not None
    assert ctx.deps.repository is ctx.repository
    # 探针为「已配置」形态（真实调用才会 error，离线不触网）


def test_build_does_not_touch_database():
    """装配路径零连接：探针调用前 analytics/app engine 未建连。"""
    ctx = _build()
    assert ctx.analytics.connect_count == 0
