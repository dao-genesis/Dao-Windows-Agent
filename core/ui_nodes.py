"""UIA 节点归一化：把各驱动异构的控件字典压成一张一致的"结构化眼睛"schema。

道法自然·R2「反馈信道偏薄」：GUI 动词回执多是 ok/文本，截屏是唯一"眼睛"；缺一个
廉价的**结构化视觉**——UIA 控件树快照。各底座（osctl `uia_children` 回 {name,type,aid,help}、
`uia_find_all` 多带 rect、别的驱动可能回 {control_type,rect:{x,y,w,h}}）形状不一，直接
交给模型是认知负担。本模块把它们统一成：

    {id, name, control_type, automation_id, help, rect, actionable}

并支持按 name（不分大小写子串）/ control_type（不分大小写，支持子串）过滤——让"看一眼
窗口里有哪些可点的东西"成为一次结构化查询，而非让模型从截屏里目测。纯逻辑、零依赖、
可离线单测；rect 缺失（uia_children 不带坐标）如实留空，绝不臆造坐标。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 可交互（actionable）控件类型：模型"下一步能点/能填"的候选。保守白名单——
# 纯展示类（Text/Image/Group/Pane 等）不算 actionable，避免把说明文字当按钮。
_ACTIONABLE_TYPES = frozenset({
    "button", "splitbutton", "menuitem", "menu", "tabitem", "tab",
    "checkbox", "radiobutton", "hyperlink", "listitem", "treeitem",
    "combobox", "edit", "document", "slider", "spinner", "custom",
})


def _first(d: dict, *keys: str, default: Any = "") -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _norm_rect(raw: Any) -> Optional[Dict[str, int]]:
    """把 rect 归一成 {x,y,w,h}；接受 (x,y,w,h) 元组/列表或已是 dict；无则 None。"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        try:
            return {"x": int(raw["x"]), "y": int(raw["y"]),
                    "w": int(raw["w"]), "h": int(raw["h"])}
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            x, y, w, h = (int(v) for v in raw)
            return {"x": x, "y": y, "w": w, "h": h}
        except (TypeError, ValueError):
            return None
    return None


def normalize_node(raw: dict, index: int = 0) -> Dict[str, Any]:
    """把一个异构控件字典归一成一致 schema。"""
    control_type = str(_first(raw, "control_type", "type", "ctype"))
    rect = _norm_rect(raw.get("rect"))
    node = {
        "id": index,
        "name": str(_first(raw, "name", "text", "title")),
        "control_type": control_type,
        "automation_id": str(_first(raw, "automation_id", "aid")),
        "help": str(_first(raw, "help", "help_text", "tooltip")),
        "rect": rect,
        "actionable": control_type.strip().lower() in _ACTIONABLE_TYPES,
    }
    return node


def normalize_nodes(children: Any, *, name: str = "", control_type: str = "",
                    actionable_only: bool = False) -> List[Dict[str, Any]]:
    """归一一批控件并按条件过滤。

    name           不分大小写子串匹配 name / automation_id / help（任一命中即留）。
    control_type   不分大小写子串匹配 control_type。
    actionable_only 仅留 actionable 控件。
    过滤后重新编号 id，保持稳定顺序。
    """
    if not isinstance(children, list):
        return []
    nodes = [normalize_node(c, i) for i, c in enumerate(children)
             if isinstance(c, dict)]

    nl = name.strip().lower()
    tl = control_type.strip().lower()
    out: List[Dict[str, Any]] = []
    for n in nodes:
        if nl:
            hay = " ".join((n["name"], n["automation_id"], n["help"])).lower()
            if nl not in hay:
                continue
        if tl and tl not in n["control_type"].lower():
            continue
        if actionable_only and not n["actionable"]:
            continue
        out.append(n)
    for i, n in enumerate(out):
        n["id"] = i
    return out


def summarize(nodes: List[Dict[str, Any]]) -> Dict[str, int]:
    """按 control_type 计数，给模型一个"这窗口大致有什么"的鸟瞰。"""
    counts: Dict[str, int] = {}
    for n in nodes:
        key = n["control_type"] or "(unknown)"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


__all__ = ["normalize_node", "normalize_nodes", "summarize"]
