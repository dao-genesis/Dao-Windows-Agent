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

import hashlib
import os
import sys
import time
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
# Document(RichEdit)——画像写任意一种都视为“编辑区”逐个尝试（与 uia_win 适配器的
# find_edit_control 同义）。静态 Text 不是编辑区：把它列为候选会命中窗口内任意说明文字
# （如 Win11 Notepad 首启的 SubtitleTextBlock），故不在此列。
_EDIT_KINDS = ("Edit", "Document")


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
        before = {w.get("id") for w in (self.os.list_windows() or [])}
        rec = self.os.launch(argv, wait_title=step.get("wait_title"))
        if rec is None:
            # 打包应用逃逸兜底：Win11 stub(如 mspaint.exe) 秒退再经应用别名重生，
            # osctl.launch 因 proc 已退而报 None——按"新窗口"再等一轮接管。
            deadline = time.time() + float(step.get("timeout", 8))
            hint = (step.get("wait_title") or "").lower()
            while time.time() < deadline and rec is None:
                for w in (self.os.list_windows() or []):
                    if w.get("id") in before:
                        continue
                    if not hint or hint in (w.get("title") or "").lower():
                        rec = w
                        break
                time.sleep(0.3)
        if rec:
            self._win[desktop] = rec.get("id")
        return {"op": "launch", "ok": rec is not None, "window": rec}

    def _op_find(self, desktop: str, step: dict) -> dict:
        kw = _spec_kw(step)
        if step.get("control_type"):
            kw.setdefault("ctype", step["control_type"])
        deadline = time.time() + float(step.get("timeout", 0))
        rect = None
        while True:
            for k in _kw_variants(kw):
                rect = self.os.uia_find(self._win.get(desktop), **k)
                if rect:
                    break
            if rect or time.time() >= deadline:
                break
            time.sleep(0.5)
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

    def _op_save_text(self, desktop: str, step: dict) -> dict:
        path = step.get("path", "")
        if not path:
            return {"op": "save_text", "ok": False, "error": "save_text 缺 path"}
        txt = None
        for k in _kw_variants({"ctype": "Edit"}):
            txt = self.os.uia_text(self._win.get(desktop), **k)
            if txt is not None:
                break
        if txt is None:
            return {"op": "save_text", "ok": False, "error": "编辑区未定位"}
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(txt)
        return {"op": "save_text", "ok": True, "path": path, "chars": len(txt)}

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
        """像素兜底：注入的 grounder → 颜色定位 → 窗口几何锚点；都无则 None（不臆造坐标）。"""
        if self.pixel_grounder is not None:
            pt = self.pixel_grounder(desktop, step)
            if pt:
                return pt
        color = step.get("color")
        if color:
            hit = self.os.find_color(tuple(color))
            if hit:
                return {"x": hit[0], "y": hit[1]}
        return self._geometry_point(desktop, step.get("target_hint", ""))

    def _geometry_point(self, desktop: str, hint: str) -> Optional[dict]:
        """窗口几何锚点兜底：hint 含方位词(画布左上/右下/中心…)时按已跟踪窗口的
        实际几何(GetWindowRect)换算屏幕坐标。仅锚点是相对约定(如左上≈30%,40%，避开
        标题栏/工具条)，几何本身是实测——比无 grounder 时直接放弃更进一步，且不臆造。"""
        win = self._win.get(desktop)
        if win is None or not hint:
            return None
        geo = getattr(self.os, "window_geometry", lambda w: None)(win)
        if not geo or geo.get("w", 0) <= 0 or geo.get("h", 0) <= 0:
            return None
        frac = None
        for kw, f in _GEOM_ANCHORS:
            if kw in hint:
                frac = f
                break
        if frac is None:
            if any(k in hint for k in ("画布", "画面", "窗口", "canvas")):
                frac = (0.5, 0.6)
            else:
                return None
        return {"x": int(geo["x"] + geo["w"] * frac[0]),
                "y": int(geo["y"] + geo["h"] * frac[1]),
                "via": "geometry"}

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
            return {"op": "locate", "ok": True, "via": pt.get("via", "pixel"), "point": pt}
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
            return {"op": "click_hint", "ok": True, "via": pt.get("via", "pixel")}
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
            return {"op": "type_hint", "ok": True, "via": pt.get("via", "pixel")}
        return {"op": "type_hint", "ok": False, "via": "none",
                "reason": "语义未命中且无像素 grounder"}

    def _op_drag_hint(self, desktop: str, step: dict) -> dict:
        a = self._pixel_point(desktop, {"target_hint": step.get("from_hint"), **step})
        b = self._pixel_point(desktop, {"target_hint": step.get("to_hint"), **step})
        if a and b:
            self.os.drag(a["x"], a["y"], b["x"], b["y"])
            via = "geometry" if "geometry" in (a.get("via"), b.get("via")) else "pixel"
            return {"op": "drag_hint", "ok": True, "via": via}
        return {"op": "drag_hint", "ok": False, "reason": "端点无法定位"}

    # —— 整机 GUI 原语（AI GUI 体系 pc_* 对等：全桌面为操作面，无需先 launch）——
    def _op_windows(self, desktop: str, step: dict) -> dict:
        return {"op": "windows", "ok": True, "windows": self.os.list_windows() or []}

    def _op_activate(self, desktop: str, step: dict) -> dict:
        title = (step.get("title") or "").lower()
        if not title:
            return {"op": "activate", "ok": False, "error": "activate 缺 title"}
        for w in (self.os.list_windows() or []):
            if title in (w.get("title") or "").lower():
                ok = bool(self.os.activate_window(w.get("id")))
                if ok:
                    self._win[desktop] = w.get("id")
                return {"op": "activate", "ok": ok, "window": w}
        return {"op": "activate", "ok": False, "error": f"无标题含 '{step.get('title')}' 的窗口"}

    def _op_click_xy(self, desktop: str, step: dict) -> dict:
        x, y = step.get("x"), step.get("y")
        if x is None or y is None:
            return {"op": "click_xy", "ok": False, "error": "click_xy 缺 x/y"}
        self.os.click(int(x), int(y), right=step.get("button") == "right")
        return {"op": "click_xy", "ok": True, "x": int(x), "y": int(y)}

    def _op_move_xy(self, desktop: str, step: dict) -> dict:
        x, y = step.get("x"), step.get("y")
        if x is None or y is None:
            return {"op": "move_xy", "ok": False, "error": "move_xy 缺 x/y"}
        self.os.move(int(x), int(y))
        return {"op": "move_xy", "ok": True}

    def _op_drag_xy(self, desktop: str, step: dict) -> dict:
        try:
            x1, y1 = int(step["x1"]), int(step["y1"])
            x2, y2 = int(step["x2"]), int(step["y2"])
        except (KeyError, TypeError, ValueError):
            return {"op": "drag_xy", "ok": False, "error": "drag_xy 缺 x1/y1/x2/y2"}
        self.os.drag(x1, y1, x2, y2)
        return {"op": "drag_xy", "ok": True}

    def _op_scroll(self, desktop: str, step: dict) -> dict:
        self.os.scroll(dy=int(step.get("dy", 0)), dx=int(step.get("dx", 0)))
        return {"op": "scroll", "ok": True}

    def _op_type_text(self, desktop: str, step: dict) -> dict:
        text = step.get("text", "")
        self.os.type_unicode(text)
        return {"op": "type_text", "ok": True, "chars": len(text)}

    def _op_clipboard_get(self, desktop: str, step: dict) -> dict:
        return {"op": "clipboard_get", "ok": True, "text": self.os.get_clipboard()}

    def _op_clipboard_set(self, desktop: str, step: dict) -> dict:
        self.os.set_clipboard(step.get("text", ""))
        return {"op": "clipboard_set", "ok": True}

    def _region_rgb(self, step: dict) -> tuple[int, int, bytes]:
        x, y = int(step.get("x", 0)), int(step.get("y", 0))
        kw = {}
        if step.get("w") is not None:
            kw["w"] = int(step["w"])
        if step.get("h") is not None:
            kw["h"] = int(step["h"])
        w, h, rgb = self.os.capture_rgb(x, y, **kw)
        return w, h, bytes(rgb)

    def _region_digest(self, step: dict) -> dict:
        w, h, rgb = self._region_rgb(step)
        return {"w": w, "h": h,
                "hash": hashlib.sha256(rgb).hexdigest()}

    @staticmethod
    def _diff_bbox(w: int, h: int, a: bytes, b: bytes) -> Optional[dict]:
        """两帧 RGB 逐像素比对，回不同像素的最小包围盒(区域内相对坐标)。"""
        x0, y0, x1, y1 = w, h, -1, -1
        stride = w * 3
        for row in range(h):
            ra, rb = a[row * stride:(row + 1) * stride], b[row * stride:(row + 1) * stride]
            if ra == rb:
                continue
            y0, y1 = min(y0, row), max(y1, row)
            for col in range(w):
                if ra[col * 3:col * 3 + 3] != rb[col * 3:col * 3 + 3]:
                    x0, x1 = min(x0, col), max(x1, col)
        if x1 < 0:
            return None
        return {"x": x0, "y": y0, "w": x1 - x0 + 1, "h": y1 - y0 + 1}

    def _op_region_hash(self, desktop: str, step: dict) -> dict:
        return {"op": "region_hash", "ok": True, **self._region_digest(step)}

    def _op_wait_change(self, desktop: str, step: dict) -> dict:
        base = self._region_digest(step)["hash"]
        deadline = time.time() + float(step.get("timeout", 10))
        while time.time() < deadline:
            cur = self._region_digest(step)["hash"]
            if cur != base:
                return {"op": "wait_change", "ok": True, "changed": True, "hash": cur}
            time.sleep(float(step.get("interval", 0.5)))
        return {"op": "wait_change", "ok": False, "changed": False,
                "error": "区域在超时内无变化"}

    def _op_where_changed(self, desktop: str, step: dict) -> dict:
        """等区域变化并回「变在哪」：变化像素的最小包围盒(绝对屏幕坐标)。"""
        w0, h0, base = self._region_rgb(step)
        deadline = time.time() + float(step.get("timeout", 10))
        while time.time() < deadline:
            w1, h1, cur = self._region_rgb(step)
            if (w1, h1) == (w0, h0) and cur != base:
                box = self._diff_bbox(w0, h0, base, cur)
                if box is None:
                    continue
                ox, oy = int(step.get("x", 0)), int(step.get("y", 0))
                return {"op": "where_changed", "ok": True, "changed": True,
                        "rect": {"x": ox + box["x"], "y": oy + box["y"],
                                 "w": box["w"], "h": box["h"]}}
            time.sleep(float(step.get("interval", 0.5)))
        return {"op": "where_changed", "ok": False, "changed": False,
                "error": "区域在超时内无变化"}

    def _op_wait_for(self, desktop: str, step: dict) -> dict:
        r = self._op_locate(desktop, {"op": "locate", **step})
        return {"op": "wait_for", "ok": r["ok"], "via": r.get("via")}

    def _op_assert_visible(self, desktop: str, step: dict) -> dict:
        r = self._op_locate(desktop, {"op": "locate", **step})
        return {"op": "assert_visible", "ok": r["ok"], "via": r.get("via")}


# 方位词 → 窗口内相对锚点（长词在前防误配；纵向 40% 起步避开标题栏/Ribbon 工具条）
_GEOM_ANCHORS: tuple[tuple[str, tuple[float, float]], ...] = (
    ("左上", (0.30, 0.40)),
    ("右上", (0.75, 0.40)),
    ("左下", (0.30, 0.80)),
    ("右下", (0.75, 0.80)),
    ("中心", (0.50, 0.60)),
    ("中央", (0.50, 0.60)),
    ("中间", (0.50, 0.60)),
    ("顶部", (0.50, 0.40)),
    ("底部", (0.50, 0.85)),
)


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
    "save_text": OsctlExecutor._op_save_text,
    "tree": OsctlExecutor._op_tree,
    "screenshot": OsctlExecutor._op_screenshot,
    "observe": OsctlExecutor._op_observe,
    "locate": OsctlExecutor._op_locate,
    "click_hint": OsctlExecutor._op_click_hint,
    "type_hint": OsctlExecutor._op_type_hint,
    "drag_hint": OsctlExecutor._op_drag_hint,
    "wait_for": OsctlExecutor._op_wait_for,
    "assert_visible": OsctlExecutor._op_assert_visible,
    "windows": OsctlExecutor._op_windows,
    "activate": OsctlExecutor._op_activate,
    "click_xy": OsctlExecutor._op_click_xy,
    "move_xy": OsctlExecutor._op_move_xy,
    "drag_xy": OsctlExecutor._op_drag_xy,
    "scroll": OsctlExecutor._op_scroll,
    "type_text": OsctlExecutor._op_type_text,
    "clipboard_get": OsctlExecutor._op_clipboard_get,
    "clipboard_set": OsctlExecutor._op_clipboard_set,
    "region_hash": OsctlExecutor._op_region_hash,
    "wait_change": OsctlExecutor._op_wait_change,
    "where_changed": OsctlExecutor._op_where_changed,
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
