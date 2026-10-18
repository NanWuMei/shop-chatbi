"""统一错误信封与 §8 错误码 → HTTP 映射（FR-1 / AC-1）。

信封：{"error": {"code", "message", "retryable", ...extra}}；时间 ISO-8601、id UUID 字符串。
"""
from __future__ import annotations

from typing import Any, Optional

# §8 错误码 → HTTP 状态映射
CODE_HTTP: dict[str, int] = {
    "E_VALIDATION": 400,
    "E_TURN_NOT_FOUND": 404,
    "E_NOT_FOUND": 404,
    "E_NAME_CONFLICT": 409,
    "E_CLARIFY_EXPIRED": 409,
    "E_REPORT_NOT_SAVEABLE": 409,
    "E_LLM_UNAVAILABLE": 502,
    "E_INTERNAL": 500,
}


class AppError(Exception):
    """业务错误：携带 §8 错误码、业务化中文文案与可选附加字段（如 existing）。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: Optional[int] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status or CODE_HTTP.get(code, 500)
        self.extra = extra or {}

    def envelope(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message, "retryable": self.retryable}
        body.update(self.extra)
        return {"error": body}


def validation_error(message: str) -> AppError:
    return AppError("E_VALIDATION", message)


def not_found(message: str = "资源不存在") -> AppError:
    return AppError("E_NOT_FOUND", message)


def turn_not_found(message: str = "本轮问数不存在或已过期") -> AppError:
    return AppError("E_TURN_NOT_FOUND", message)


def name_conflict(existing: dict) -> AppError:
    return AppError("E_NAME_CONFLICT", "已有同名报表", extra={"existing": existing})


def clarify_expired(message: str = "澄清已失效，请基于原问题重新提问") -> AppError:
    return AppError("E_CLARIFY_EXPIRED", message)


def report_not_saveable(message: str = "该轮结果不可保存为报表") -> AppError:
    return AppError("E_REPORT_NOT_SAVEABLE", message)


def internal_error(message: str = "服务内部处理失败，请稍后重试") -> AppError:
    return AppError("E_INTERNAL", message)
