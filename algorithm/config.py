"""环境配置（SDD §8）：无 key 时读取不报错，仅问数时才产生 E_LLM_UNAVAILABLE。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _env(name: str) -> Optional[str]:
    v = os.environ.get(name)
    return v if v else None


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # LLM（OpenAI 兼容协议，代码不出现厂商名）
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_model_fast: Optional[str] = None
    llm_model_strong: Optional[str] = None
    llm_timeout_seconds: int = 30
    # Embedding（可选增强）
    emb_base_url: Optional[str] = None
    emb_api_key: Optional[str] = None
    emb_model: Optional[str] = None
    emb_dim: int = 1024
    # 资源与限幅
    resources_path: Optional[str] = None
    row_limit_default: int = 500
    row_limit_max: int = 1000

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def emb_configured(self) -> bool:
        return bool(self.emb_base_url and self.emb_api_key and self.emb_model)


def load_settings(env: Optional[dict] = None) -> Settings:
    """从环境变量读取；全缺省时返回默认值且不抛错。"""
    getter = (lambda n: env.get(n) or None) if env is not None else _env

    def gi(name: str, default: int) -> int:
        if env is not None:
            v = env.get(name)
            if not v:
                return default
            try:
                return int(v)
            except ValueError:
                return default
        return _env_int(name, default)

    return Settings(
        llm_base_url=getter("LLM_BASE_URL"),
        llm_api_key=getter("LLM_API_KEY"),
        llm_model=getter("LLM_MODEL"),
        llm_model_fast=getter("LLM_MODEL_FAST"),
        llm_model_strong=getter("LLM_MODEL_STRONG"),
        llm_timeout_seconds=gi("LLM_TIMEOUT_SECONDS", 30),
        emb_base_url=getter("EMB_BASE_URL"),
        emb_api_key=getter("EMB_API_KEY"),
        emb_model=getter("EMB_MODEL"),
        emb_dim=gi("EMB_DIM", 1024),
        resources_path=getter("RESOURCES_PATH"),
        row_limit_default=gi("ROW_LIMIT_DEFAULT", 500),
        row_limit_max=gi("ROW_LIMIT_MAX", 1000),
    )
