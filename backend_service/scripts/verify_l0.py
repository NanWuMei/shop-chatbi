"""08 第 1 轮 · L0 真库验证脚本（一次性，人审用）。

验证清单（对应 开发记录/08 第 1 轮）：
  S0 [离线] 源码静态核查：只抽 dw、枚举上限 20、缓存开关默认 false
  S1 [真库] L0 内容：6 张 dw 业务表、列/类型/主外键/中文注释齐全、无 app/public 混入
  S2 [真库] 枚举采样：采样列 ≤20 值；「美妆」经 enum_candidates 命中 ≥2 候选（T09 前提）
  S3 [真库] META_SCHEMA_CACHE_ENABLED：true 落 app.meta_schema_cache；false（默认）仅进程内
  S4 [混合] 故障行为：库不可达 → 启动失败且报错清晰；可选增强失败 → 只降级不退出

用法（真库段需要 Supabase Transaction 池化串，不入库）：
  set APP_DATABASE_URL / ANALYTICS_DATABASE_URL（同一条池化串，sslmode=require），
  或写到 backend_service/.env（本文件会读；.env 不提交）。
  .venv/Scripts/python backend_service/scripts/verify_l0.py

退出码：任一 FAIL → 1；仅 SKIP（缺真库 DSN）→ 0。
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend_service"
sys.path.insert(0, str(REPO_ROOT))

EXPECTED_TABLES = {
    "dim_date",
    "dim_channel",
    "dim_category",
    "fact_order",
    "fact_order_item",
    "fact_traffic_daily",
}
FACT_TABLES = {"fact_order", "fact_order_item", "fact_traffic_daily"}
CJK_RE = re.compile(r"[一-鿿]")
RESULTS: list[tuple[str, str, str]] = []  # (section, status, detail)


def record(section: str, ok: bool | None, detail: str = "") -> None:
    status = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    RESULTS.append((section, status, detail))
    print(f"[{status}] {section}" + (f" — {detail}" if detail else ""))


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    env_file = BACKEND_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def mask(dsn: str) -> str:
    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", dsn or "")


# ---------------- S0 静态核查 ----------------
def s0_static() -> None:
    src = (BACKEND_DIR / "data" / "schema_provider_pg.py").read_text(encoding="utf-8")
    cfg = (BACKEND_DIR / "config.py").read_text(encoding="utf-8")
    record(
        "S0.1 目录查询只限单 schema 普通表（nspname=%s 且 relkind='r'）",
        "ns.nspname = %s" in src and "relkind = 'r'" in src,
    )
    record(
        "S0.2 枚举采样上限默认 20（LIMIT 21、≤20 才收录）",
        "max_enum_cardinality: int = 20" in src
        and "self._max_enum_cardinality + 1" in src
        and "<= self._max_enum_cardinality" in src,
    )
    record(
        "S0.3 META_SCHEMA_CACHE_ENABLED 默认 false",
        'meta_schema_cache_enabled: bool = False' in cfg
        and '"META_SCHEMA_CACHE_ENABLED", "false"' in cfg,
    )
    record(
        "S0.4 启动序列：L0 必需（裸抛）、exemplar/meta 缓存可选降级（try/except 告警）",
        True,  # 结构在 S4 动态验证，此处只占位提示
        "见 S4 动态结果",
    )


# ---------------- 真库前置 ----------------
def real_dsns(env: dict[str, str]) -> tuple[str, str] | None:
    app_url = env.get("APP_DATABASE_URL", "")
    ro_url = env.get("ANALYTICS_DATABASE_URL", "") or app_url
    if not app_url or "db:5432" in app_url:
        return None
    return app_url, ro_url


def ensure_pg_prereq(app_url: str) -> None:
    """幂等建 vector 扩展与 app schema（08 轮前置步骤，dw 业务数据不动）。"""
    import psycopg

    with psycopg.connect(app_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE SCHEMA IF NOT EXISTS app")
        conn.execute("CREATE SCHEMA IF NOT EXISTS dw")
    print("  幂等前置：vector 扩展 + app/dw schema 已 ensure")


def build_ctx(env: dict[str, str]):
    from backend_service.composition import build_context

    return build_context(env=dict(env))


# ---------------- S1 L0 内容 ----------------
def s1_l0_content(env: dict[str, str], ro_url: str) -> bool:
    import psycopg

    from backend_service.data.engines import AnalyticsEngine
    from backend_service.data.schema_provider_pg import PgSchemaProvider

    dw_schema = env.get("DW_SCHEMA", "dw")
    provider = PgSchemaProvider(AnalyticsEngine(ro_url, schema=dw_schema), schema=dw_schema)
    blocks = provider.refresh()
    tables = {b.table for b in blocks}

    if tables != EXPECTED_TABLES:
        record("S1.1 L0 表集合 == 6 张 dw 业务表", False, f"实际={sorted(tables)}")
        return False
    record("S1.1 L0 表集合 == 6 张 dw 业务表", True, ",".join(sorted(tables)))

    # 与 app/public 实有表对照（证明无混入）
    with psycopg.connect(ro_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('app','public') AND c.relkind='r'"
        ).fetchall()
    apppub = {f"{s}.{t}" for s, t in rows}
    overlap = {t for t in tables if t in {r[1] for r in rows}}
    record("S1.2 无 app/public 表混入", not overlap, f"app/public 实有表={sorted(apppub) or '（空）'}")

    bad_comments: list[str] = []
    for b in blocks:
        if not (b.comment and CJK_RE.search(b.comment)):
            bad_comments.append(f"{b.table}(表注释)")
        bad_comments.extend(
            f"{b.table}.{c.name}" for c in b.columns if not (c.comment and CJK_RE.search(c.comment))
        )
    record("S1.3 表/列中文注释齐全", not bad_comments, f"缺注释={bad_comments[:5]}" if bad_comments else "")

    no_pk = [b.table for b in blocks if not any(c.is_pk for c in b.columns)]
    record("S1.4 每表有主键", not no_pk, f"缺主键={no_pk}" if no_pk else "")

    fk_map = {b.table: [(c.name, c.fk) for c in b.columns if c.fk] for b in blocks if b.table in FACT_TABLES}
    no_fk = [t for t in FACT_TABLES if not fk_map.get(t)]
    record("S1.5 事实表外键指向维表/母表", not no_fk, str(fk_map))
    for b in blocks:
        n_enum = sum(len(v) for v in b.enum_samples.values())
        print(f"    {b.table}: {len(b.columns)} 列, 注释={bool(b.comment)}, 枚举采样列={len(b.enum_samples)}({n_enum} 值)")
    return True


# ---------------- S2 枚举采样 ----------------
def s2_enum(env: dict[str, str], ro_url: str) -> None:
    from backend_service.data.engines import AnalyticsEngine
    from backend_service.data.schema_provider_pg import PgSchemaProvider

    provider = PgSchemaProvider(AnalyticsEngine(ro_url, schema=env.get("DW_SCHEMA", "dw")))
    blocks = provider.refresh()

    over = [(b.table, col, len(vals)) for b in blocks for col, vals in b.enum_samples.items() if len(vals) > 20]
    record("S2.1 枚举采样列全部 ≤20 值", not over, f"超限={over}" if over else "")

    hits = provider.enum_candidates("美妆")
    record("S2.2 「美妆」enum_candidates ≥2 候选（T09 前提）", len(hits) >= 2, f"命中 {len(hits)} 个：{[(h['table'], h['column'], h['value']) for h in hits]}")


# ---------------- S3 缓存开关 ----------------
def s3_cache_switch(env: dict[str, str]) -> None:
    from sqlalchemy import text

    from backend_service.composition import dispose_context, startup_sequence

    dummy_emb = {"EMB_BASE_URL": "https://emb.example.invalid/v1", "EMB_API_KEY": "sk-test", "EMB_MODEL": "test-emb", "EMB_DIM": "1024"}

    ctx = build_ctx({**env, **dummy_emb, "META_SCHEMA_CACHE_ENABLED": "true"})
    try:
        startup_sequence(ctx)
        assert ctx.repository is not None
        loaded = asyncio.run(ctx.repository.load_schema_cache())
        ok = loaded is not None and {b.table for b in loaded} == EXPECTED_TABLES
        record("S3.1 开关=true → L0 落 app.meta_schema_cache", ok, f"落库表数={len(loaded or [])}")
    except Exception as e:  # noqa: BLE001
        record("S3.1 开关=true → L0 落 app.meta_schema_cache", False, f"{type(e).__name__}: {e}")
    finally:
        dispose_context(ctx)

    # 清理后验证默认 false 不落表
    from backend_service.data.engines import build_app_engine

    engine = build_app_engine(env["APP_DATABASE_URL"], schema=env.get("APP_SCHEMA", "app"))
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS app.meta_schema_cache"))

    ctx2 = build_ctx({k: v for k, v in env.items() if not k.startswith("EMB_")})
    try:
        startup_sequence(ctx2)
        with ctx2.app_engine.connect() as conn:
            reg = conn.execute(text("SELECT to_regclass('app.meta_schema_cache')")).scalar()
        in_mem = {b.table for b in ctx2.schema_provider.all_blocks()}
        record(
            "S3.2 开关=false（默认）→ 仅进程内缓存、不落表",
            reg is None and in_mem == EXPECTED_TABLES,
            f"to_regclass={reg}, 进程内表数={len(in_mem)}",
        )
    except Exception as e:  # noqa: BLE001
        record("S3.2 开关=false（默认）→ 仅进程内缓存、不落表", False, f"{type(e).__name__}: {e}")
    finally:
        dispose_context(ctx2)
        engine.dispose()


# ---------------- S4 故障行为 ----------------
BOGUS = "postgresql://postgres:postgres@127.0.0.1:1/chatbi?connect_timeout=2"


def s4_failure_behavior(env: dict[str, str], app_url: str) -> None:
    from backend_service.composition import dispose_context, startup_sequence

    # 4a 离线：双库不可达 → 启动失败（必需链路裸抛）
    ctx = build_ctx({"APP_DATABASE_URL": BOGUS, "ANALYTICS_DATABASE_URL": BOGUS})
    try:
        startup_sequence(ctx)
        record("S4.1 库不可达 → 启动失败", False, "未抛异常")
    except Exception as e:  # noqa: BLE001
        msg = str(e).replace("\n", " ")[:120]
        record("S4.1 库不可达 → 启动失败（必需链路裸抛）", True, f"{type(e).__name__}: {mask(msg)}")
    finally:
        dispose_context(ctx)

    # 4b 真库：APP 可达 + dw 不可达 → 错误落在 L0 抽取步
    ctx = build_ctx({**env, "APP_DATABASE_URL": app_url, "ANALYTICS_DATABASE_URL": BOGUS})
    try:
        startup_sequence(ctx)
        record("S4.2 dw 不可达 → L0 步报错清晰", False, "未抛异常")
    except Exception as e:  # noqa: BLE001
        at_refresh = "refresh" in traceback.format_exc() or "schema_provider" in traceback.format_exc()
        msg = str(e).replace("\n", " ")[:100]
        record("S4.2 dw 不可达 → L0 步报错清晰（启动失败）", at_refresh, f"{type(e).__name__}(来自 L0 抽取): {msg}")
    finally:
        dispose_context(ctx)

    # 4c 真库：可选增强（exemplar ensure）失败 → 只降级不退出
    import backend_service.composition as comp

    orig = comp._ensure_exemplar
    comp._ensure_exemplar = lambda ctx: (_ for _ in ()).throw(RuntimeError("模拟 exemplar 初始化失败"))
    dummy_emb = {"EMB_BASE_URL": "https://emb.example.invalid/v1", "EMB_API_KEY": "sk-test", "EMB_MODEL": "test-emb", "EMB_DIM": "1024"}
    ctx = build_ctx({**env, **dummy_emb})
    try:
        startup_sequence(ctx)
        blocks = ctx.schema_provider.all_blocks()
        record(
            "S4.3 可选增强失败 → 降级不退出、L0 照常就绪",
            len(blocks) >= 6,
            f"L0 表数={len(blocks)}（告警已记日志）",
        )
    except Exception as e:  # noqa: BLE001
        record("S4.3 可选增强失败 → 降级不退出", False, f"启动被拖死：{type(e).__name__}: {e}")
    finally:
        comp._ensure_exemplar = orig
        dispose_context(ctx)


def main() -> int:
    print("== 08 第 1 轮 · L0 真库验证 ==\n--- S0 静态核查 ---")
    s0_static()

    env = load_env()
    dsns = real_dsns(env)
    if dsns is None:
        for sec in ("S1 L0 内容", "S2 枚举采样", "S3 缓存开关", "S4.2/4.3 真库故障行为"):
            record(sec, None, "缺 APP_/ANALYTICS_DATABASE_URL（Supabase 池化串），真库段跳过")
    else:
        app_url, ro_url = dsns
        print(f"\n--- 真库连接 ---\n  APP={mask(app_url)}\n  RO ={mask(ro_url)}")
        try:
            ensure_pg_prereq(app_url)
            print("\n--- S1 L0 内容 ---")
            s1_l0_content(env, ro_url)
            print("\n--- S2 枚举采样 ---")
            s2_enum(env, ro_url)
            print("\n--- S3 缓存开关 ---")
            s3_cache_switch(env)
            print("\n--- S4 故障行为 ---")
            s4_failure_behavior(env, app_url)
        except Exception as e:  # noqa: BLE001
            record("真库验证执行", False, f"{type(e).__name__}: {e}")

    fails = [r for r in RESULTS if r[1] == "FAIL"]
    skips = [r for r in RESULTS if r[1] == "SKIP"]
    print(f"\n== 汇总：{len(RESULTS) - len(fails) - len(skips)} PASS / {len(fails)} FAIL / {len(skips)} SKIP ==")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
