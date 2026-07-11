"""AI GUI 操作体系绑定层：把级别②/③ 动作计划落到 vendored agentctl 底座（osctl）。

彻底规避「截图+点击」低能操作——语义优先：先按 target/target_hint 走 UIA 控件树
（`uia_find` 命中 Name/AutomationId/HelpText → 取控件自报 rect → 点击/置值/取值），
仅当语义地板抓不到时才降级像素通道（注入的 grounder / 颜色定位）。坐标永远是最后手段。

绑定层不改上游 osctl 源码（见 core/gui/agentctl/VENDOR.md），仅在导入前把 vendored
目录挂上 sys.path。osctl 在导入期按平台选后端（Win→UIA / Linux→X11），故只在 guest
（Windows）或带 X 的 Linux 上可实机运行；无对应库时 `load_osctl` 抛错，调用方据此
退回 dry-run。翻译逻辑本身以假 osctl 注入即可离线单测。
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable, Optional

_VENDOR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "gui", "agentctl"))

# 像素兜底 grounder 契约：grounder(desktop, step) -> {"x": int, "y": int} | None
Grounder = Callable[[str, dict], Optional[dict]]


def load_osctl(vendor_dir: Optional[str] = None) -> Any:
    """把 vendored agentctl 目录挂上 sys.path 并导入 osctl（无对应平台后端即抛 ImportError）。"""
    d = os.path.abspath(vendor_dir or _VENDOR_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import osctl  # noqa: E402 — 延迟导入：平台后端在导入期决定
    return osctl


def _spec_kw(spec) -> dict:
    """把 find/target 规格({by,value} 字典或裸字符串)译成 uia_* 的 name/ctype 关键字。

    画像以 ``{"by": "control_type", "value": "Edit"}`` 指控件类型——误当 name 会命中
    同名菜单项(如 Notepad 的 Edit 菜单)，故按 by 分流到 ctype/name。
    """
    if isinstance(spec, str):
        return {"name": spec}
    if isinstance(spec, dict):
        by, value = spec.get("by"), spec.get("value")
        if by == "control_type":
            return {"ctype": value}
        if value is not None:
            return {"name": value}
    return {}


# 文本编辑区在不同代 Windows 控件型不同：经典应用是 Edit，Win11 新 Notepad/WinUI 是
# Document(RichEdit)，部分是 Text——画像写任意一种都视为“编辑区”逐个尝试（与
# uia_win 适配器的 find_edit_control 同义）。
_EDIT_KINDS = ("Edit", "Document", "Text")


def _kw_variants(kw: dict) -> list[dict]:
    if kw.get("ctype") in _EDIT_KINDS and not kw.get("name"):
        return [{"ctype": c} for c in _EDIT_KINDS]
    return [kw]


class OsctlExecutor:
    """把一份动作计划(`{verb, steps:[{op,...}]}`)逐步落到 osctl。

    osctl 经构造注入（真机传 load_osctl() 结果；单测传假模块）——所有底座访问都过它，
    故语义优先的调用次序可离线断言。
    """

    def __init__(self, osctl: Any, pixel_grounder: Optional[Grounder] = None,
                 shot_dir: str = "") -> None:
        self.os = osctl
        self.pixel_grounder = pixel_grounder
        self.shot_dir = shot_dir or os.path.join(os.path.expanduser("~"), ".dao", "shots")
        self._win: dict[str, int] = {}  # desktop -> 窗口句柄(hwnd/xid)

    # —— 入口：执行整份计划 ——
    def run(self, desktop: str, plan: dict) -> dict:
        results = [self._step(desktop, s) for s in (plan.get("steps") or [])]
        ok = all(r.get("ok") for r in results) if results else True
        return {"verb": plan.get("verb"), "ok": ok, "results": results}

    def _step(self, desktop: str, step: dict) -> dict:
        op = step.get("op")
        try:
            fn = _OPS.get(op)
            if fn is None:
                return {"op": op, "ok": False, "error": f"未知 op '{op}'"}
            return fn(self, desktop, step)
        except Exception as exc:  # noqa: BLE001 — 单步失败如实回报，不炸整份计划
            return {"op": op, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # —— 级别② UIA（语义）——
    def _op_launch(self, desktop: str, step: dict) -> dict:
        argv = [step["exe"], *(step.get("args") or [])]
        rec = self.os.launch(argv, wait_title=step.get("wait_title"))
        if rec:
            self._win[desktop] = rec.get("id")
        return {"op": "launch", "ok": rec is not None, "window": rec}

    def _op_find(self, desktop: str, step: dict) -> dict:
        kw = _spec_kw(step)
        if step.get("control_type"):
            kw.setdefault("ctype", step["control_type"])
        rect = None
        for k in _kw_variants(kw):
            rect = self.os.uia_find(self._win.get(desktop), **k)
            if rect:
                break
        return {"op": "find", "ok": rect is not None, "rect": rect}

    def _op_click(self, desktop: str, step: dict) -> dict:
        rect = self.os.uia_find(self._win.get(desktop), **_spec_kw(step.get("target")))
        ok = bool(rect is not None and self.os.click_center(rect))
        return {"op": "click", "ok": ok, "rect": rect}

    def _op_set_value(self, desktop: str, step: dict) -> dict:
        ok = False
        for k in _kw_variants(_spec_kw(step.get("target"))):
            ok = bool(self.os.uia_set_value(self._win.get(desktop),
                                            step.get("text", ""), **k))
            if ok:
                break
        return {"op": "set_value", "ok": ok}

    def _op_get_text(self, desktop: str, step: dict) -> dict:
        txt = None
        for k in _kw_variants(_spec_kw(step.get("target"))):
            txt = self.os.uia_text(self._win.get(desktop), **k)
            if txt:
                break
        return {"op": "get_text", "ok": txt is not None, "text": txt}

    def _op_invoke(self, desktop: str, step: dict) -> dict:
        return {"op": "invoke", "ok": bool(self.os.uia_invoke(
            self._win.get(desktop), **_spec_kw(step.get("target"))))}

    def _op_menu(self, desktop: str, step: dict) -> dict:
        path = step.get("path") or []
        if not path:
            return {"op": "menu", "ok": False, "error": "menu 缺 path"}
        ok = bool(self.os.uia_context(self._win.get(desktop), path[0], *path[1:]))
        return {"op": "menu", "ok": ok}

    def _op_keys(self, desktop: str, step: dict) -> dict:
        self.os.hotkey(step.get("keys", ""))
        return {"op": "keys", "ok": True}

    def _op_tree(self, desktop: str, step: dict) -> dict:
        children = self.os.uia_children(self._win.get(desktop))
        return {"op": "tree", "ok": True, "children": children}

    def _op_screenshot(self, desktop: str, step: dict) -> dict:
        os.makedirs(self.shot_dir, exist_ok=True)
        path = step.get("path") or os.path.join(self.shot_dir, f"{desktop or 'screen'}.png")
        self.os.screenshot(path)
        return {"op": "screenshot", "ok": True, "path": path}

    # —— 级别③ 视觉（语义优先 → 像素兜底）——
    def _semantic_rect(self, desktop: str, hint: str) -> Any:
        win = self._win.get(desktop)
        if win is None or not hint:
            return None
        return self.os.uia_find(win, name=hint)

    def _pixel_point(self, desktop: str, step: dict) -> Optional[dict]:
        """像素兜底：优先注入的 grounder，其次颜色定位；都无则 None（不臆造坐标）。"""
        if self.pixel_grounder is not None:
            pt = self.pixel_grounder(desktop, step)
            if pt:
                return pt
        color = step.get("color")
        if color:
            hit = self.os.find_color(tuple(color))
            if hit:
                return {"x": hit[0], "y": hit[1]}
        return None

    def _op_observe(self, desktop: str, step: dict) -> dict:
        w, h, _rgb = self.os.capture_rgb()
        return {"op": "observe", "ok": True, "size": [w, h]}

    def _op_locate(self, desktop: str, step: dict) -> dict:
        hint = step.get("target_hint", "")
        rect = self._semantic_rect(desktop, hint)
        if rect is not None:
            return {"op": "locate", "ok": True, "via": "semantic", "rect": rect}
        pt = self._pixel_point(desktop, step)
        if pt:
            return {"op": "locate", "ok": True, "via": "pixel", "point": pt}
        return {"op": "locate", "ok": False, "via": "none",
                "reason": "语义未命中且无像素 grounder（不臆造坐标）"}

    def _op_click_hint(self, desktop: str, step: dict) -> dict:
        hint = step.get("target_hint", "")
        rect = self._semantic_rect(desktop, hint)
        if rect is not None:
            return {"op": "click_hint", "ok": bool(self.os.click_center(rect)), "via": "semantic"}
        pt = self._pixel_point(desktop, step)
        if pt:
            self.os.click(pt["x"], pt["y"])
            return {"op": "click_hint", "ok": True, "via": "pixel"}
        return {"op": "click_hint", "ok": False, "via": "none",
                "reason": "语义未命中且无像素 grounder"}

    def _op_type_hint(self, desktop: str, step: dict) -> dict:
        hint = step.get("target_hint", "")
        text = step.get("text", "")
        win = self._win.get(desktop)
        if win is not None and hint and self.os.uia_set_value(win, text, name=hint):
            return {"op": "type_hint", "ok": True, "via": "semantic"}
        pt = self._pixel_point(desktop, step)
        if pt:
            self.os.click(pt["x"], pt["y"])
            self.os.type_unicode(text)
            return {"op": "type_hint", "ok": True, "via": "pixel"}
        return {"op": "type_hint", "ok": False, "via": "none",
                "reason": "语义未命中且无像素 grounder"}

    def _op_drag_hint(self, desktop: str, step: dict) -> dict:
        a = self._pixel_point(desktop, {"target_hint": step.get("from_hint"), **step})
        b = self._pixel_point(desktop, {"target_hint": step.get("to_hint"), **step})
        if a and b:
            self.os.drag(a["x"], a["y"], b["x"], b["y"])
            return {"op": "drag_hint", "ok": True, "via": "pixel"}
        return {"op": "drag_hint", "ok": False, "reason": "端点无法定位"}

    def _op_wait_for(self, desktop: str, step: dict) -> dict:
        r = self._op_locate(desktop, {"op": "locate", **step})
        return {"op": "wait_for", "ok": r["ok"], "via": r.get("via")}

    def _op_assert_visible(self, desktop: str, step: dict) -> dict:
        r = self._op_locate(desktop, {"op": "locate", **step})
        return {"op": "assert_visible", "ok": r["ok"], "via": r.get("via")}


# op → 处理函数（一张表，避免长 if 链）
_OPS: dict[str, Callable[[OsctlExecutor, str, dict], dict]] = {
    "launch": OsctlExecutor._op_launch,
    "find": OsctlExecutor._op_find,
    "click": OsctlExecutor._op_click,
    "set_value": OsctlExecutor._op_set_value,
    "get_text": OsctlExecutor._op_get_text,
    "invoke": OsctlExecutor._op_invoke,
    "menu": OsctlExecutor._op_menu,
    "keys": OsctlExecutor._op_keys,
    "tree": OsctlExecutor._op_tree,
    "screenshot": OsctlExecutor._op_screenshot,
    "observe": OsctlExecutor._op_observe,
    "locate": OsctlExecutor._op_locate,
    "click_hint": OsctlExecutor._op_click_hint,
    "type_hint": OsctlExecutor._op_type_hint,
    "drag_hint": OsctlExecutor._op_drag_hint,
    "wait_for": OsctlExecutor._op_wait_for,
    "assert_visible": OsctlExecutor._op_assert_visible,
}


def make_uia_driver(osctl: Optional[Any] = None,
                    pixel_grounder: Optional[Grounder] = None) -> Callable[[str, dict], Any]:
    """构造级别② UIA driver：driver(desktop, plan) -> 执行结果。osctl 省略则实机加载。"""
    ex = OsctlExecutor(osctl or load_osctl(), pixel_grounder=pixel_grounder)
    return ex.run


def make_grounder(osctl: Optional[Any] = None,
                  pixel_grounder: Optional[Grounder] = None) -> Callable[[str, dict], Any]:
    """构造级别③ 视觉 grounder：grounder(desktop, plan) -> 执行结果（语义优先·同一执行器）。"""
    ex = OsctlExecutor(osctl or load_osctl(), pixel_grounder=pixel_grounder)
    return ex.run
