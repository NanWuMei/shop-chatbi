"""08 第 5 轮 · 资源接通总验证（人审用）。

只验证「资源能否被算法访问」，不跑完整问数链路、不执行任何业务 SQL：
  R1 L0：dw 六表/列/类型/注释齐全，无 app/public 混入
  R2 L1：dict（metrics/entities/calendar）经 loader 加载，实体来源均能在 L0 找到
  R3 templates：可加载，SQL 仅作 few-shot/模板（含 {start}/{end} 槽位，非即执行业务 SQL）
  R4 exemplar：表存在且含种子，向量路与词命中路都能召回
  R5 装配：经后端 build_context + startup_sequence，Deps 五类依赖全部接通
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

EXPECTED_TABLES = {"dim_date", "dim_channel", "dim_category", "fact_order", "fact_order_item", "fact_traffic_daily"}
RESULTS: list[tuple[str, bool, str]] = []


def rec(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    env_file = REPO_ROOT / "backend_service" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def main() -> int:
    from backend_service.composition import build_context, dispose_context, startup_sequence

    env = load_env()
    env.setdefault("RESOURCES_PATH", str(REPO_ROOT / "algorithm" / "resources"))

    ctx = build_context(env=env)
    try:
        startup_sequence(ctx)

        # R1 L0
        blocks = ctx.schema_provider.all_blocks()
        tables = {b.table for b in blocks}
        rec("R1.1 L0 六张 dw 业务表", tables == EXPECTED_TABLES, f"实际={sorted(tables)}")
        all_comment = all(b.comment for b in blocks) and all(c.comment for b in blocks for c in b.columns)
        rec("R1.2 表/列中文注释齐全", all_comment)
        rec("R1.3 无 app/public 混入", not (tables & {"sessions", "messages", "reports", "exemplar", "meta_schema_cache"}))

        # R2 L1
        res = ctx.deps.resources
        rec("R2.1 metrics 加载", len(res.metrics) >= 4, f"{len(res.metrics)} 条")
        rec("R2.2 entities 加载", len(res.entities) >= 5, f"{len(res.entities)} 条")
        rec("R2.3 calendar 加载", len(res.calendar) >= 10, f"{len(res.calendar)} 区间")
        # 实体来源对照 L0
        l0_cols = {(b.table, c.name) for b in blocks for c in b.columns}
        bad = []
        for e in res.entities:
            src = e.get("source") or {}
            t = src.get("table")
            cols = src.get("columns") or ([src["column"]] if src.get("column") else [])
            if t and t not in tables:
                bad.append(f"{e.get('id')}:{t}(表不在L0)")
            for c in cols:
                if t and (t, c) not in l0_cols:
                    bad.append(f"{e.get('id')}:{t}.{c}")
        rec("R2.4 实体来源均能在 L0 找到", not bad, f"失配={bad}" if bad else "")

        # R3 templates
        rec("R3.1 templates 加载", len(res.templates) >= 5, f"{len(res.templates)} 条")
        slot_ok = all("{start}" in (t.get("sql") or "") and "{end}" in (t.get("sql") or "") for t in res.templates)
        rec("R3.2 模板 SQL 为槽位模板（{start}/{end}），非即执行业务 SQL", slot_ok)

        # R4 exemplar 两路召回
        repo = ctx.repository
        rec("R4.1 repository 已装配（EMB 齐全）", repo is not None)
        if repo is not None:
            kw_hits = asyncio.run(repo.search_exemplars(keywords=["渠道", "GMV"], top_k=3))
            rec("R4.2 词命中路召回", len(kw_hits) > 0, f"top1={kw_hits[0].question}" if kw_hits else "空")
            emb = ctx.deps.embedding
            if emb is not None and emb.available:
                vec = asyncio.run(emb.embed(["各渠道成交额排名"]))[0]
                vec_hits = asyncio.run(repo.search_exemplars(embedding=vec, top_k=3))
                rec("R4.3 向量路召回", len(vec_hits) > 0 and vec_hits[0].score > 0.5,
                    " / ".join(f"{h.question}({h.score:.3f})" for h in vec_hits))
            else:
                rec("R4.3 向量路召回", False, "embedding 客户端不可用")

        # R5 装配完整性
        d = ctx.deps
        rec("R5.1 Deps 五类依赖接通",
            all([d.settings, d.llm, d.schema_provider, d.query_runner, d.resources]) and d.repository is not None and d.embedding is not None)
        rec("R5.2 chain_runner 已装配", callable(ctx.chain_runner))
    finally:
        dispose_context(ctx)

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n== 汇总：{len(RESULTS) - len(fails)} PASS / {len(fails)} FAIL ==")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
