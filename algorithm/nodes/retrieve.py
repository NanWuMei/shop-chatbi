"""S3 检索 retrieve（SDD §3-S3）：编排四源上下文。

L0 schema_blocks（必有，六表全量返回供 S4/S5/lint）；L1 caliber/entity（有则）；
exemplars：vector 成功则 top3~5，embedding 未配置/失败回 lexical 且 mode=lexical（trace 标注）。
检索只作 S4/S5 输入上下文，不作授权、不做事后比对。
"""
from __future__ import annotations

from typing import Any

from ..protocols import EmbeddingUnavailableError, deps_from_config, emit
from ..retrieval import lexical, vector
from langchain_core.runnables import RunnableConfig

from ..state import ChainState, RetrievalContext, RetrievalMode


async def retrieve(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    deps = deps_from_config(config)
    emit(deps, "node_started", {"node": "S3"})
    notes: list[str] = []

    intent = state.intent
    keywords = lexical.keywords_of(
        intent.metrics if intent else [],
        intent.dimensions if intent else [],
        intent.filters if intent else [],
        [intent.time_expr] if intent else [],
    )
    question = state.clarified_question or state.question

    # ① L0 库结构（总有；为空则返回空上下文不报错）
    blocks = deps.schema_provider.all_blocks()
    if not blocks:
        ctx = RetrievalContext(schema_blocks=[], mode=RetrievalMode.LEXICAL)
        out = {
            "retrieval": ctx,
            "retrieval_mode": RetrievalMode.LEXICAL.value,
            "trace_path": state.trace_path + ["S3"],
            "trace_notes": state.trace_notes + ["S3: L0 为空，返回空上下文"],
        }
        emit(deps, "node_finished", {"node": "S3"})
        return out
    blocks = lexical.rank_blocks(blocks, keywords)

    # ②③ L1 口径/实体（可选增强）
    caliber_defs = lexical.match_resource_items(deps.resources.metrics, keywords)
    entity_defs = lexical.match_resource_items(deps.resources.entities, keywords)

    # ④ exemplars：vector 优先，降级 lexical
    exemplars = []
    mode = RetrievalMode.LEXICAL
    if deps.embedding is not None and deps.repository is not None:
        try:
            exemplars = await vector.vector_search_exemplars(
                question, embedding=deps.embedding, repository=deps.repository, top_k=5
            )
            mode = RetrievalMode.VECTOR
        except EmbeddingUnavailableError as e:
            notes.append(f"S3: embedding 不可用，降级 lexical（{e}）")
    if mode == RetrievalMode.LEXICAL and deps.repository is not None:
        exemplars = await deps.repository.search_exemplars(keywords=keywords, top_k=5)
    if mode == RetrievalMode.LEXICAL:
        notes.append("S3: mode=lexical")

    ctx = RetrievalContext(
        schema_blocks=blocks,
        caliber_defs=caliber_defs,
        entity_defs=entity_defs,
        exemplars=exemplars,
        mode=mode,
    )
    out = {
        "retrieval": ctx,
        "retrieval_mode": mode.value,
        "trace_path": state.trace_path + ["S3"],
        "trace_notes": state.trace_notes + notes,
    }
    emit(deps, "node_finished", {"node": "S3"})
    return out
