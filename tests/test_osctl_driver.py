"""AI GUI 绑定层单测：以假 osctl 注入，离线断言计划→osctl 调用的翻译与语义优先次序。"""
from __future__ import annotations

from core.adapter.osctl_driver import OsctlExecutor, make_uia_driver


class FakeOsctl:
    """记录调用序列的假底座；uia_find 命中与否由 rects 表控制。"""

    def __init__(self, rects=None):
        self.calls = []
        self.rects = rects or {}  # name -> rect(或 None)

    def launch(self, argv, wait_title=None):
        self.calls.append(("launch", tuple(argv), wait_title))
        return {"id": 4321, "title": wait_title or argv[0]}

    def list_windows(self):
        self.calls.append(("list_windows",))
        return []

    def uia_find(self, win, name=None, ctype=None):
        self.calls.append(("uia_find", win, name, ctype))
        return self.rects.get(name)

    def click_center(self, rect):
        self.calls.append(("click_center", rect))
        return True

    def click(self, x, y, right=False):
        self.calls.append(("click", x, y))

    def uia_set_value(self, win, text, name=None):
        self.calls.append(("uia_set_value", win, text, name))
        return name in self.rects

    def uia_text(self, win, name=None):
        self.calls.append(("uia_text", win, name))
        return "hello"

    def uia_invoke(self, win, name=None):
        self.calls.append(("uia_invoke", win, name))
        return True

    def uia_context(self, win, first, *rest):
        self.calls.append(("uia_context", win, first, rest))
        return True

    def uia_children(self, win):
        self.calls.append(("uia_children", win))
        return [{"name": "OK"}]

    def hotkey(self, spec):
        self.calls.append(("hotkey", spec))

    def screenshot(self, path):
        self.calls.append(("screenshot", path))
        return path

    def capture_rgb(self, x=0, y=0, w=None, h=None):
        self.calls.append(("capture_rgb",))
        return (1920, 1080, b"")

    def find_color(self, color, *a, **k):
        self.calls.append(("find_color", color))
        return (100, 200)

    def type_unicode(self, text):
        self.calls.append(("type_unicode", text))

    def drag(self, x0, y0, x1, y1, *a, **k):
        self.calls.append(("drag", x0, y0, x1, y1))

    def names(self):
        return [c[0] for c in self.calls]


def test_launch_binds_window_then_uia_ops():
    fake = FakeOsctl(rects={"保存": object()})
    ex = OsctlExecutor(fake)
    plan = {"verb": "save", "steps": [
        {"op": "launch", "exe": "notepad.exe"},
        {"op": "click", "target": "保存"},
    ]}
    res = ex.run("dao_s1_notepad", plan)
    assert res["ok"] is True
    assert fake.names() == ["list_windows", "launch", "uia_find", "click_center"]
    # 窗口句柄从 launch 绑定，传给后续 uia_find
    assert fake.calls[2][1] == 4321


def test_uia_verbs_translate():
    fake = FakeOsctl(rects={"标题": object(), "文本框": object()})
    ex = OsctlExecutor(fake)
    plan = {"verb": "edit", "steps": [
        {"op": "launch", "exe": "app.exe"},
        {"op": "set_value", "target": "文本框", "text": "道"},
        {"op": "get_text", "target": "标题"},
        {"op": "invoke", "target": "标题"},
        {"op": "menu", "path": ["文件", "另存为"]},
        {"op": "keys", "keys": "ctrl+s"},
        {"op": "tree"},
    ]}
    res = ex.run("d", plan)
    assert res["ok"] is True
    got = fake.names()
    assert got == ["list_windows", "launch", "uia_set_value", "uia_text",
                   "uia_invoke", "uia_context", "hotkey", "uia_children"]


def test_vision_semantic_first_then_pixel():
    # 语义命中：click_hint 走 uia_find→click_center，绝不触碰像素通道
    fake = FakeOsctl(rects={"确定按钮": object()})
    ex = OsctlExecutor(fake)
    ex._win["d"] = 10
    r = ex._step("d", {"op": "click_hint", "target_hint": "确定按钮"})
    assert r["ok"] and r["via"] == "semantic"
    assert "find_color" not in fake.names() and "click" not in fake.names()


def test_vision_pixel_fallback_when_no_semantic():
    fake = FakeOsctl(rects={})  # uia_find 全落空
    ex = OsctlExecutor(fake)
    ex._win["d"] = 10
    # 无 grounder、无 color → 不臆造坐标，如实回报失败
    r = ex._step("d", {"op": "click_hint", "target_hint": "找不到的"})
    assert not r["ok"] and r["via"] == "none"
    # 给颜色 → 走像素兜底点击
    r2 = ex._step("d", {"op": "click_hint", "target_hint": "找不到的", "color": [255, 0, 0]})
    assert r2["ok"] and r2["via"] == "pixel"
    assert ("find_color", (255, 0, 0)) in fake.calls


def test_injected_pixel_grounder_wins_over_color():
    fake = FakeOsctl(rects={})
    hits = []

    def grounder(desktop, step):
        hits.append(step.get("target_hint"))
        return {"x": 7, "y": 9}

    ex = OsctlExecutor(fake, pixel_grounder=grounder)
    ex._win["d"] = 10
    r = ex._step("d", {"op": "click_hint", "target_hint": "目标"})
    assert r["ok"] and r["via"] == "pixel"
    assert hits == ["目标"] and ("click", 7, 9) in fake.calls


def test_type_hint_semantic_then_pixel():
    fake = FakeOsctl(rects={"输入框": object()})
    ex = OsctlExecutor(fake)
    ex._win["d"] = 10
    r = ex._step("d", {"op": "type_hint", "target_hint": "输入框", "text": "无为"})
    assert r["ok"] and r["via"] == "semantic"
    assert ("uia_set_value", 10, "无为", "输入框") in fake.calls


def test_unknown_op_and_step_error_isolated():
    fake = FakeOsctl()
    ex = OsctlExecutor(fake)
    r = ex._step("d", {"op": "nope"})
    assert not r["ok"] and "未知 op" in r["error"]


def test_make_uia_driver_returns_callable():
    fake = FakeOsctl(rects={"x": object()})
    driver = make_uia_driver(fake)
    out = driver("d", {"verb": "v", "steps": [{"op": "launch", "exe": "a"},
                                              {"op": "click", "target": "x"}]})
    assert out["ok"] is True


class GeomOsctl(FakeOsctl):
    def __init__(self, geo=None, rects=None):
        super().__init__(rects=rects)
        self.geo = geo

    def window_geometry(self, win):
        self.calls.append(("window_geometry", win))
        return self.geo

    def drag(self, x1, y1, x2, y2):
        self.calls.append(("drag", x1, y1, x2, y2))


def test_geometry_fallback_drag_canvas_corners():
    fake = GeomOsctl(geo={"x": 100, "y": 50, "w": 1000, "h": 800})
    ex = OsctlExecutor(fake)
    ex._win["d"] = 10
    r = ex._step("d", {"op": "drag_hint", "from_hint": "画布左上", "to_hint": "画布右下"})
    assert r["ok"] and r["via"] == "geometry"
    assert ("drag", 100 + 300, 50 + 320, 100 + 750, 50 + 640) in fake.calls


def test_geometry_fallback_wait_for_canvas():
    fake = GeomOsctl(geo={"x": 0, "y": 0, "w": 800, "h": 600})
    ex = OsctlExecutor(fake)
    ex._win["d"] = 10
    r = ex._step("d", {"op": "wait_for", "target_hint": "画图窗口的画布区域", "timeout": 0})
    assert r["ok"] and r["via"] == "geometry"


def test_geometry_fallback_honest_when_no_window_or_no_keyword():
    fake = GeomOsctl(geo={"x": 0, "y": 0, "w": 800, "h": 600})
    ex = OsctlExecutor(fake)
    # 未跟踪窗口 → 不臆造
    r = ex._step("d", {"op": "click_hint", "target_hint": "画布中心"})
    assert not r["ok"] and r["via"] == "none"
    # 有窗口但 hint 无方位/画布词 → 不臆造
    ex._win["d"] = 10
    r2 = ex._step("d", {"op": "click_hint", "target_hint": "确定按钮"})
    assert not r2["ok"] and r2["via"] == "none"
    # 有方位词 → 几何兜底
    r3 = ex._step("d", {"op": "click_hint", "target_hint": "画布中心"})
    assert r3["ok"] and r3["via"] == "geometry"


def test_geometry_fallback_degenerate_geometry_refused():
    fake = GeomOsctl(geo={"x": 0, "y": 0, "w": 0, "h": 0})
    ex = OsctlExecutor(fake)
    ex._win["d"] = 10
    r = ex._step("d", {"op": "click_hint", "target_hint": "画布中心"})
    assert not r["ok"] and r["via"] == "none"


class PcOsctl(FakeOsctl):
    """整机 GUI 原语(pc_* 对等)的假底座：窗口/剪贴板/滚轮/区域指纹。"""

    def __init__(self, windows=None, frames=None, rects=None):
        super().__init__(rects=rects)
        self.windows = windows or []
        self.frames = frames or [b"\x00"]  # capture_rgb 逐次弹出的帧内容
        self.clip = ""

    def list_windows(self):
        self.calls.append(("list_windows",))
        return self.windows

    def activate_window(self, win):
        self.calls.append(("activate_window", win))
        return True

    def move(self, x, y):
        self.calls.append(("move", x, y))

    def scroll(self, dy=0, dx=0):
        self.calls.append(("scroll", dy, dx))

    def get_clipboard(self):
        self.calls.append(("get_clipboard",))
        return self.clip

    def set_clipboard(self, text):
        self.calls.append(("set_clipboard", text))
        self.clip = text

    def capture_rgb(self, x=0, y=0, w=None, h=None):
        self.calls.append(("capture_rgb", x, y, w, h))
        frame = self.frames[0] if len(self.frames) == 1 else self.frames.pop(0)
        return (4, 4, frame)


def test_pc_windows_and_activate_scopes_window():
    fake = PcOsctl(windows=[{"id": 7, "title": "无标题 - 记事本"}])
    ex = OsctlExecutor(fake)
    r = ex._step("", {"op": "windows"})
    assert r["ok"] and r["windows"][0]["id"] == 7
    r2 = ex._step("", {"op": "activate", "title": "记事本"})
    assert r2["ok"] and ("activate_window", 7) in fake.calls
    # activate 之后成为语义作用域：find/tree 用该窗口句柄
    assert ex._win[""] == 7
    r3 = ex._step("", {"op": "activate", "title": "不存在的窗口"})
    assert not r3["ok"]
    r4 = ex._step("", {"op": "activate"})
    assert not r4["ok"]


def test_pc_input_primitives_translate():
    fake = PcOsctl()
    ex = OsctlExecutor(fake)
    assert ex._step("", {"op": "click_xy", "x": 10, "y": 20})["ok"]
    assert ex._step("", {"op": "move_xy", "x": 1, "y": 2})["ok"]
    assert ex._step("", {"op": "drag_xy", "x1": 0, "y1": 0, "x2": 5, "y2": 5})["ok"]
    assert ex._step("", {"op": "scroll", "dy": -3})["ok"]
    assert ex._step("", {"op": "type_text", "text": "道"})["ok"]
    got = fake.names()
    assert got == ["click", "move", "drag", "scroll", "type_unicode"]
    # 缺坐标如实报错，不臆造
    assert not ex._step("", {"op": "click_xy"})["ok"]
    assert not ex._step("", {"op": "drag_xy", "x1": 1})["ok"]


def test_pc_clipboard_roundtrip():
    fake = PcOsctl()
    ex = OsctlExecutor(fake)
    assert ex._step("", {"op": "clipboard_set", "text": "无为"})["ok"]
    r = ex._step("", {"op": "clipboard_get"})
    assert r["ok"] and r["text"] == "无为"


def test_pc_region_hash_and_wait_change():
    fake = PcOsctl(frames=[b"\x00"])
    ex = OsctlExecutor(fake)
    r = ex._step("", {"op": "region_hash", "x": 0, "y": 0, "w": 4, "h": 4})
    assert r["ok"] and len(r["hash"]) == 64
    # 帧不变 → 超时如实报未变化
    r2 = ex._step("", {"op": "wait_change", "timeout": 0.1, "interval": 0.01})
    assert not r2["ok"] and r2["changed"] is False
    # 帧变化 → 命中
    fake2 = PcOsctl(frames=[b"\x00", b"\x01"])
    ex2 = OsctlExecutor(fake2)
    r3 = ex2._step("", {"op": "wait_change", "timeout": 2, "interval": 0.01})
    assert r3["ok"] and r3["changed"] is True
