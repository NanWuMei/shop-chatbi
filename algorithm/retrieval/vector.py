"""向量检索通道（SDD §5/§8.2：可选增强）。

embed 问题文本 → 经 Repository 取向量近邻 exemplar top_k。
embedding 客户端不可用/抛错时向上抛 EmbeddingUnavailableError（降级信号），
由 S3 节点统一降级 lexical——本模块不自行兜底吞错。
"""
from __future__ import annotations

from ..protocols import EmbeddingClient, EmbeddingUnavailableError, Repository
from ..state import Exemplar


async def vector_search_exemplars(
    question: str,
    *,
    embedding: EmbeddingClient,
    repository: Repository,
    top_k: int = 5,
) -> list[Exemplar]:
    """向量通道召回 exemplar；任何 embedding 失败都以 EmbeddingUnavailableError 上抛。"""
    if not embedding.available:
        raise EmbeddingUnavailableError("embedding 未配置")
    try:
        vecs = await embedding.embed([question])
    except EmbeddingUnavailableError:
        raise
    except Exception as e:  # 客户端其他异常统一映射为降级信号
        raise EmbeddingUnavailableError(str(e)) from e
    if not vecs:
        raise EmbeddingUnavailableError("embedding 返回为空")
    return await repository.search_exemplars(embedding=vecs[0], top_k=top_k)
