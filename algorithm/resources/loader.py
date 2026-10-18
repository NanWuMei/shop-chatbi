"""资源加载器（SDD §7.1）：从注入路径读 L1 dict YAML 与 S2 templates YAML。

路径缺失/目录为空 → 空资源对象（Resources 全空），不报错——「无增强」是合法形态。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..protocols import Resources

_DICT_KIND_BY_STEM = {
    "metrics": "metrics",
    "metric": "metrics",
    "entities": "entities",
    "entity": "entities",
    "calendar": "calendar",
    "time-calendar": "calendar",
    "time_calendar": "calendar",
}


def load_resources(path: str | Path | None) -> Resources:
    """加载资源目录；不存在/为空/文件损坏均不抛错（损坏文件跳过并忽略）。"""
    res = Resources()
    if not path:
        return res
    root = Path(path)
    if not root.exists() or not root.is_dir():
        return res
    _load_dict_dir(root / "dict", res)
    _load_templates_dir(root / "templates", res)
    return res


def _read_yaml(p: Path) -> Any:
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_dict_dir(d: Path, res: Resources) -> None:
    if not d.is_dir():
        return
    for f in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
        data = _read_yaml(f)
        if data is None:
            continue
        kind = _DICT_KIND_BY_STEM.get(f.stem.lower())
        if kind == "metrics":
            res.metrics.extend(_as_list(data, key="metrics"))
        elif kind == "entities":
            res.entities.extend(_as_list(data, key="entities"))
        elif kind == "calendar":
            res.calendar.update(_as_calendar(data))
        else:
            # 未识别文件名：按内容顶层键归类
            if isinstance(data, dict):
                if "metrics" in data:
                    res.metrics.extend(_as_list(data, key="metrics"))
                if "entities" in data:
                    res.entities.extend(_as_list(data, key="entities"))
                if "calendar" in data or "periods" in data:
                    res.calendar.update(_as_calendar(data))


def _load_templates_dir(d: Path, res: Resources) -> None:
    if not d.is_dir():
        return
    for f in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
        data = _read_yaml(f)
        if data is None:
            continue
        for t in _as_list(data, key="templates"):
            if isinstance(t, dict) and t.get("id"):
                res.templates.append(t)


def _as_list(data: Any, *, key: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if key == "templates" and data.get("id"):
            return [data]
        # 单条字典形态（无顶层键包装）
        if not v and key != "templates" and data:
            return [data]
    return []


def _as_calendar(data: Any) -> dict[str, Any]:
    """日历 YAML → {档期名: [start, end]}；兼容 {calendar: {...}} 与 {periods: [...]} 两种写法。"""
    out: dict[str, Any] = {}
    if not isinstance(data, dict):
        return out
    body = data.get("calendar", data)
    if isinstance(body, dict):
        for k, v in body.items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                out[str(k)] = [str(v[0]), str(v[1])]
    periods = data.get("periods")
    if isinstance(periods, list):
        for p in periods:
            if isinstance(p, dict) and p.get("key") and p.get("start") and p.get("end"):
                out[str(p["key"])] = [str(p["start"]), str(p["end"])]
    return out
