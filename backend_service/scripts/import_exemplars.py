"""08 第 4 轮 · exemplar 种子导入 + 检索验证（一次性，人审用）。

流程（不改算法链路、不动 dw 业务数据）：
  1. exemplar 表 + hnsw 索引幂等 ensure（走 storage/ddl.exemplar_ddl，与启动序列同源）；
  2. 读 algorithm/resources/exemplars/seed.yaml →（EMB_* 齐全时）调 Embedding API 向量化
     → repository.upsert_exemplar 落 app.exemplar（source=seed）；
     id 用 question 的 uuid5，重复导入幂等（ON CONFLICT 覆盖，不产生重复行）；
  3. 检索验证：向量路（有 EMB）+ 词命中降级路（无 EMB 也能跑）。

用法：
  连接串走 backend_service/.env（APP_DATABASE_URL），EMB_* 同文件或环境变量；
  .venv/Scripts/python backend_service/scripts/import_exemplars.py
  无 EMB_* 时自动只跑词命中降级验证（embedding 列留空）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend_service"
sys.path.insert(0, str(REPO_ROOT))

SEED_YAML = REPO_ROOT / "algorithm" / "resources" / "exemplars" / "seed.yaml"
_ID_NS = uuid.UUID("6f1c3d2a-9b2c-4c3a-9f4e-0f3f6d9b8a10")  # 固定命名空间，question → 稳定 uuid5

# 检索验证用例：(问句, 词命中关键词, 期望召回的 seed 问句关键词)
SEARCH_CASES = [
    ("618各渠道成交额排个名", ["渠道", "GMV", "排名"], "各渠道GMV"),
    ("哪个类目退货最多，看前三", ["类目", "退货率", "TopN"], "退货率最高的三个类目"),
    ("新客老客成交占比", ["占比", "新老客"], "新客和老客的GMV占比"),
    ("今年618和去年比怎么样", ["同比", "GMV"], "比去年同期"),
]


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


def emb_dim(env: dict[str, str]) -> int:
    return int(env.get("EMB_DIM", "1024"))


async def embed_all(client, texts: list[str]) -> list[list[float]]:
    return await client.embed(texts)


def main() -> int:
    from sqlalchemy import text

    from algorithm.config import load_settings
    from algorithm.state import Exemplar
    from backend_service.data.engines import build_app_engine
    from backend_service.data.pg_exemplar_repo import PgExemplarRepository
    from backend_service.storage.ddl import exemplar_ddl

    env = load_env()
    app_url = env.get("APP_DATABASE_URL", "")
    if not app_url:
        print("[FAIL] 缺 APP_DATABASE_URL"); return 1
    schema = env.get("APP_SCHEMA", "app")
    dim = emb_dim(env)
    settings = load_settings(env)

    # 1. 幂等 ensure exemplar 表 + hnsw（与启动序列同一 DDL 来源，不另建）
    engine = build_app_engine(app_url, schema=schema)
    with engine.begin() as conn:
        for stmt in exemplar_ddl(schema, dim):
            conn.execute(text(stmt))
    print(f"[PASS] exemplar 表 + hnsw 索引已 ensure（app schema, vector({dim})，来源 storage/ddl.exemplar_ddl）")

    # 2. 读种子 →（可选）向量化 → upsert
    seed = yaml.safe_load(SEED_YAML.read_text(encoding="utf-8"))["exemplars"]
    print(f"  读入种子 {len(seed)} 条")

    repo = PgExemplarRepository(engine, schema=schema, emb_dim=dim)
    embeddings: list[list[float] | None] = [None] * len(seed)
    if settings.emb_configured:
        from algorithm.llm.embeddings import OpenAICompatibleEmbeddingClient

        client = OpenAICompatibleEmbeddingClient(settings)
        questions = [s["question"] for s in seed]
        vectors = asyncio.run(embed_all(client, questions))
        for i, v in enumerate(vectors):
            if len(v) != dim:
                print(f"[FAIL] 第 {i} 条维度不符：期望 {dim} 实际 {len(v)}"); return 1
        embeddings = vectors
        print(f"[PASS] Embedding API 向量化 {len(vectors)} 条，维度 {dim} 与 EMB_DIM 一致")
    else:
        print("[SKIP] 未配置 EMB_*：导入不带向量（embedding=NULL），向量路验证跳过")

    async def upsert_all() -> None:
        for s, vec in zip(seed, embeddings):
            ex = Exemplar(
                id=str(uuid.uuid5(_ID_NS, s["question"])),
                question=s["question"], sql=s["sql"],
                chart_type=s["chart_type"], tags=list(s["tags"]),
            )
            await repo.upsert_exemplar(ex, vec)

    asyncio.run(upsert_all())
    with engine.connect() as conn:
        n = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.exemplar")).scalar()
        nvec = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.exemplar WHERE embedding IS NOT NULL")).scalar()
    print(f"[PASS] 导入完成：app.exemplar 共 {n} 行（含向量 {nvec} 行）")

    # 幂等：再跑一遍导入，行数不变
    asyncio.run(upsert_all())
    with engine.connect() as conn:
        n2 = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.exemplar")).scalar()
    ok = n2 == n == len(seed)
    print(f"[{'PASS' if ok else 'FAIL'}] 幂等：重复导入后仍 {n2} 行（无重复）")
    if not ok:
        return 1

    # 3. 检索验证
    print("\n--- 检索验证 ---")
    fails = 0
    for question, kws, expect in SEARCH_CASES:
        if settings.emb_configured:
            from algorithm.llm.embeddings import OpenAICompatibleEmbeddingClient

            vec = asyncio.run(embed_all(OpenAICompatibleEmbeddingClient(settings), [question]))[0]
            hits = asyncio.run(repo.search_exemplars(embedding=vec, top_k=3))
            top = hits[0] if hits else None
            hit_ok = bool(top and expect in top.question)
            fails += 0 if hit_ok else 1
            detail = " / ".join(f"{h.question}({h.score:.3f})" for h in hits)
            print(f"[{'PASS' if hit_ok else 'FAIL'}] 向量路「{question}」→ {detail}")
        hits_kw = asyncio.run(repo.search_exemplars(keywords=kws, top_k=3))
        top = hits_kw[0] if hits_kw else None
        hit_ok = bool(top and expect in top.question)
        fails += 0 if hit_ok else 1
        detail = " / ".join(f"{h.question}(score={h.score})" for h in hits_kw)
        print(f"[{'PASS' if hit_ok else 'FAIL'}] 词命中「{question}」{kws} → {detail}")

    print(f"\n== 汇总：{'全部通过' if fails == 0 else f'{fails} 项未达标'} ==")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
