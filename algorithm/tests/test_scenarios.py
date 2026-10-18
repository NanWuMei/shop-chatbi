"""T01~T15 离线场景回归（TR-14.2，AC-15/16）。

每条场景可被 -k 逐一点名（如 pytest algorithm -k t05）；
覆盖 FR-20 特殊点：T05/T09 澄清、T10/T15 拒答、T06 AOV 分母、T07 三段+changes、
T08 同比、T14 limit=3、T12 多轮承接、T13 饼图占比。
"""
from __future__ import annotations

import pytest

from algorithm.graph import run_chain

from .conftest import SCENARIO_IDS, assert_expect, load_scenario, make_deps


@pytest.mark.parametrize("sid", SCENARIO_IDS, ids=SCENARIO_IDS)
async def test_scenario(sid: str) -> None:
    scn = load_scenario(sid)
    deps, llm, runner = make_deps(scn)
    tid = f"test-{sid}"
    result = await run_chain(
        question=scn["question"],
        deps=deps,
        thread_id=tid,
        conversation_summary=scn.get("conversation_summary", ""),
    )
    assert_expect(result, scn["expect"], runner, llm)

    reentry = scn.get("reentry")
    if reentry:  # T05：澄清确认后重入，应出判定答案
        assert result.clarify is not None, "reentry 场景第一轮必须产出澄清卡"
        result2 = await run_chain(
            clarified_question=reentry["clarified_question"],
            clarify_id=result.clarify.clarify_id,
            deps=deps,
            thread_id=tid,
        )
        assert_expect(result2, reentry["expect"], runner, llm)
