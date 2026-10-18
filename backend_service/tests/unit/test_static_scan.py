"""TR-12.3 / TR-4.4 / B11 / B30：静态扫描——分层 import 纪律 + 报文白名单。

- AST 扫描 backend_service/ 全部非测试源码：下层不得反向依赖上层；路由层不触 SQLAlchemy/psycopg/算法；
  algorithm 仅允许协议/入口白名单（算法包零修改约束的静态面）；
- 报文白名单：answer 出参键集合 == FR-7 十一键；backend_service/ 源码不出现 dual_line（B30）。
"""
import ast
import pathlib
import uuid

from algorithm.state import ChartType

from backend_service.application import mappers

from ..conftest import make_answer_result

API_DIR = pathlib.Path(__file__).resolve().parents[2]

# algorithm 白名单：协议/入口/共享 DTO（TR-4.4：后端只 import 其协议与入口）
ALGORITHM_ALLOWED = {
    "algorithm",
    "algorithm.config",
    "algorithm.llm.client",
    "algorithm.llm.embeddings",
    "algorithm.protocols",
    "algorithm.retrieval.schema_extractor",
    "algorithm.resources.loader",
    "algorithm.state",
}

# 层级禁入：{层目录: 禁止的 import 顶层/前缀}
WEB_STACK = ("fastapi", "sse_starlette", "starlette", "uvicorn")
LAYER_FORBIDDEN: dict[str, tuple[str, ...]] = {
    "storage": WEB_STACK + ("backend_service.application", "backend_service.routes", "backend_service.data", "psycopg"),
    "data": WEB_STACK + ("backend_service.application", "backend_service.routes"),
    "application": WEB_STACK + ("sqlalchemy", "psycopg", "backend_service.routes", "backend_service.data", "backend_service.storage"),
    "routes": ("sqlalchemy", "psycopg", "algorithm", "backend_service.application", "backend_service.data", "backend_service.storage", "backend_service.composition", "backend_service.main"),
}


def _iter_source_files():
    for path in sorted(API_DIR.rglob("*.py")):
        rel = path.relative_to(API_DIR).as_posix()
        if rel.startswith("tests"):
            continue
        yield path, rel


def _resolved_full_names(path: pathlib.Path, tree: ast.AST) -> list[str]:
    """解析 import 为完整模块名（含相对 import 归一）。"""
    rel_parts = path.relative_to(API_DIR).with_suffix("").parts  # 如 ("application", "mappers")
    pkg_parts = rel_parts[:-1]
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                mod = tuple(node.module.split(".")) if node.module else ()
                names.append(".".join(base + mod))
            elif node.module:
                names.append(node.module)
    return names


def test_layered_import_discipline():
    violations: list[str] = []
    for path, rel in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        layer = rel.split("/")[0] if "/" in rel else ""
        forbidden = LAYER_FORBIDDEN.get(layer, ())
        for full in _resolved_full_names(path, tree):
            top = full.split(".")[0]
            if top == "algorithm" and full not in ALGORITHM_ALLOWED:
                violations.append(f"{rel}: 越权 import 算法内部 {full}")
            for f in forbidden:
                if full == f or full.startswith(f + ".") or (f.startswith("backend_service.") and full == f):
                    violations.append(f"{rel}: {layer} 层禁止 import {full}")
    assert not violations, "\n".join(violations)


def test_no_dual_line_anywhere():
    """B30：禁漏字段/图表型 dual_line 不得出现在 api 源码。"""
    hits = [str(rel) for path, rel in _iter_source_files() if "dual_line" in path.read_text(encoding="utf-8")]
    assert not hits, f"dual_line 泄漏于: {hits}"


def test_chart_type_enum_has_no_dual_line():
    assert not any(v == "dual_line" for v in ChartType.__members__.values())


def test_answer_payload_whitelist_keys():
    """FR-7 十一键白名单：出参镜像五业务字段 + 后端信封字段，绝无 sql/trace/query_spec。"""
    result = make_answer_result(turn_id=str(uuid.uuid4()))
    _event, frame = mappers.terminal_frame(result, turn_id="t", session_id="s")
    assert set(frame) == {
        "turn_id", "session_id", "question", "table", "chart", "insight",
        "caliber", "comparison", "data_time_range", "queried_at", "saveable",
    }
    mtype, payload, internal = mappers.terminal_message(result, turn_id="t", session_id="s")
    assert set(internal) == {"sql", "trace", "query_spec"}  # internal 三键仅在落库侧
    assert "sql" not in payload and "trace" not in payload and "query_spec" not in payload


def test_stage_mapping_frozen():
    """stage 映射写死（B3）：S1/S2-S4/S5-S8，不许新增任意节点。"""
    assert mappers.STAGE_BY_NODE == {
        "S1": ("understanding", "正在理解问题"),
        "S2": ("checking_caliber", "正在核对口径"),
        "S3": ("checking_caliber", "正在核对口径"),
        "S4": ("checking_caliber", "正在核对口径"),
        "S5": ("querying", "正在取数"),
        "S6": ("querying", "正在取数"),
        "S7": ("querying", "正在取数"),
        "S8": ("querying", "正在取数"),
    }
