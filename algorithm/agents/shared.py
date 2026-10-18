"""LLM 节点公共小工具：节点内失败重试 1 次（SDD §8.1）。"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from ..protocols import LLMUnavailableError
from ..state import E_LLM_UNAVAILABLE, ErrorPayload

# (LLMUnavailableError, ValueError)：未配置/网络/超时/结构化输出不合 schema 均视同失败
_RETRYABLE = (LLMUnavailableError, ValueError)


async def call_with_retry(
    fn: Callable[[], Awaitable[BaseModel]],
) -> tuple[BaseModel | None, int, Exception | None]:
    """调用 LLM，失败重试 1 次（共最多 2 次）。

    返回 (结果, 实际调用次数, 最后的异常)；成功时异常为 None。
    """
    last_err: Exception | None = None
    attempts = 0
    for _ in range(2):
        attempts += 1
        try:
            return await fn(), attempts, None
        except _RETRYABLE as e:
            last_err = e
    return None, attempts, last_err


def llm_error_payload(err: Exception | None) -> ErrorPayload:
    """LLM 故障统一映射 error 载荷（E_LLM_UNAVAILABLE, retryable=true）。"""
    return ErrorPayload(
        code=E_LLM_UNAVAILABLE,
        message=f"模型服务暂不可用：{err}" if err else "模型服务暂不可用",
        retryable=True,
    )


def error_state(state: Any, payload: ErrorPayload, llm_calls: int) -> dict[str, Any]:
    from ..state import Action

    return {
        "error": payload,
        "final_action": Action.ERROR,
        "llm_calls": state.llm_calls + llm_calls,
    }
