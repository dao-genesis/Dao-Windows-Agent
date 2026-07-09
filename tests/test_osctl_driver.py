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
    assert fake.names() == ["launch", "uia_find", "click_center"]
    # 窗口句柄从 launch 绑定，传给后续 uia_find
    assert fake.calls[1][1] == 4321


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
    assert got == ["launch", "uia_set_value", "uia_text", "uia_invoke",
                   "uia_context", "hotkey", "uia_children"]


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
