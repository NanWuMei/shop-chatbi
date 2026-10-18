"""ChatBI 算法问数链路（SDD-算法应用 v0.4）。

对外唯一入口 run_chain，唯一返回契约 ChainResult。
"""

from .state import ChainResult  # noqa: F401

__all__ = ["ChainResult", "build_graph", "run_chain"]


def __getattr__(name: str):  # 延迟加载，避免 import 包时强依赖编排框架可用性
    if name in ("build_graph", "run_chain"):
        from . import graph

        return getattr(graph, name)
    raise AttributeError(name)
