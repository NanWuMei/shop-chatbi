"""import 边界静态扫描（边界铁律，TR-14.3）。

- 全包不 import psycopg/asyncpg/sqlalchemy（算法不直连库，psycopg 只在 requirements 供后端步使用）；
- Coder 不持有执行工具（gen.py 的 deps 只碰 llm）；
- Understand 不引用 schema/repo/runner（deps 只碰 llm）；
- Writer 看不到 SQL（state 上不取 sql/lineage/lint 字段）。
AST 级判定，不受注释/docstring 干扰。
"""
from __future__ import annotations

import ast
import pathlib

ALG = pathlib.Path(__file__).resolve().parents[1]  # algorithm/

_FORBIDDEN_IMPORTS = {"psycopg", "psycopg2", "asyncpg", "sqlalchemy", "pymysql"}


def _imported_modules(tree: ast.AST) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def _attr_uses(tree: ast.AST, base_name: str) -> set[str]:
    """收集 base.<attr> 形式读取过的属性名（含 deps.xxx / state.xxx）。"""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == base_name:
            out.add(node.attr)
    return out


def test_no_db_driver_import_anywhere() -> None:
    offenders: list[str] = []
    for f in ALG.rglob("*.py"):
        if "__pycache__" in f.parts:
            continue
        mods = _imported_modules(ast.parse(f.read_text(encoding="utf-8")))
        bad = mods & _FORBIDDEN_IMPORTS
        if bad:
            offenders.append(f"{f.relative_to(ALG)}: {sorted(bad)}")
    assert not offenders, f"算法包不得 import 数据库驱动：{offenders}"


def _deps_attrs(rel: str) -> set[str]:
    tree = ast.parse((ALG / rel).read_text(encoding="utf-8"))
    return _attr_uses(tree, "deps")


def test_coder_has_no_execution_tool() -> None:
    for rel in ("agents/coder/gen.py", "agents/coder/subgraph.py"):
        used = _deps_attrs(rel)
        assert "query_runner" not in used, f"{rel} 持有执行工具：{used}"


def test_understand_blind_to_schema_repo_runner() -> None:
    used = _deps_attrs("agents/understand/node.py")
    assert used <= {"llm", "settings", "on_event"}, f"understand 越界引用：{used}"


def test_writer_blind_to_sql_and_runner() -> None:
    src = (ALG / "agents/writer/node.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    state_attrs = _attr_uses(tree, "state")
    assert not (state_attrs & {"sql", "lineage", "lint_errors", "lint_rounds"}), (
        f"writer 读到 SQL 侧字段：{state_attrs}"
    )
    used = _deps_attrs("agents/writer/node.py")
    assert "query_runner" not in used
