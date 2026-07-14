"""浏览器画像（CDP 语义面）单测：假 browser 注入，纯逻辑离线跑。"""
from __future__ import annotations

from core.profiles.builtin import browser as browser_mod
from core.profiles.builtin import build_default_registry


class _FakeBrowser:
    def __init__(self):
        self.calls = []
        self.closed = False

    def navigate(self, url, *a, **k):
        self.calls.append(("navigate", url))
        return url

    def click(self, selector, by_text=False, *a, **k):
        self.calls.append(("click", selector, by_text))
        return True

    def select_option(self, selector, *, value=None, **k):
        self.calls.append(("select_option", selector, value))
        return True

    def close(self):
        self.closed = True


def _adapter(fake=None):
    factory = (lambda: fake) if fake is not None else None
    return browser_mod._ADAPTER(browser_mod.PROFILE, browser_factory=factory)


def test_registered_as_universal_layer():
    reg = build_default_registry()
    prof = reg.get("browser")
    assert prof.is_universal and prof.handle == "browser"
    assert prof.verb("navigate") and prof.verb("wait_visible")
    assert not prof.validate()


def test_dry_run_without_cdp():
    ad = _adapter()
    inst = ad.launch(workdir=".")
    res = ad.invoke(inst, "click", selector="#ok", by_text=False)
    assert res.ok and res.value["dry_run"] is True
    assert res.value["method"] == "click" and res.value["args"] == ["#ok", False]


def test_positional_binding_and_kwonly():
    fake = _FakeBrowser()
    ad = _adapter(fake)
    inst = ad.launch(workdir=".")
    assert ad.invoke(inst, "navigate", url="https://x").ok
    assert ad.invoke(inst, "click", selector="登录", by_text=True).ok
    assert ad.invoke(inst, "select_option", selector="#sel", value="v1").ok
    assert fake.calls == [
        ("navigate", "https://x"),
        ("click", "登录", True),
        ("select_option", "#sel", "v1"),
    ]


def test_new_semantic_verbs_registered_and_bound():
    reg = build_default_registry()
    prof = reg.get("browser")
    for name in ("double_click", "context_click", "dnd", "scroll",
                 "set_value", "set_file_input", "press_enter",
                 "wait_for", "wait_change", "close"):
        assert prof.verb(name), f"缺动词 {name}"

    class _Rich:
        def __init__(self):
            self.calls = []

        def dnd(self, source, target):
            self.calls.append(("dnd", source, target)); return True

        def set_file_input(self, selector, files):
            self.calls.append(("set_file_input", selector, files))

        def press_enter(self):
            self.calls.append(("press_enter",))

        def wait_for(self, expr_js, timeout=10.0):
            self.calls.append(("wait_for", expr_js, timeout)); return True

    fake = _Rich()
    ad = _adapter(fake)
    inst = ad.launch(workdir=".")
    assert ad.invoke(inst, "dnd", source="#a", target="#b").ok
    assert ad.invoke(inst, "set_file_input", selector="#f",
                     files=["/tmp/a.png"]).ok
    assert ad.invoke(inst, "press_enter").ok
    assert ad.invoke(inst, "wait_for", expr_js="1==1", timeout=3).ok
    assert fake.calls == [
        ("dnd", "#a", "#b"),
        ("set_file_input", "#f", ["/tmp/a.png"]),
        ("press_enter",),
        ("wait_for", "1==1", 3),
    ]


def test_unknown_verb_and_error_reported():
    fake = _FakeBrowser()
    ad = _adapter(fake)
    inst = ad.launch(workdir=".")
    assert not ad.invoke(inst, "nope").ok

    def boom(*a, **k):
        raise RuntimeError("炸")
    fake.navigate = boom
    res = ad.invoke(inst, "navigate", url="https://x")
    assert not res.ok and "RuntimeError" in res.error


def test_shutdown_closes_browser():
    fake = _FakeBrowser()
    ad = _adapter(fake)
    inst = ad.launch(workdir=".")
    ad.shutdown(inst)
    assert fake.closed and not inst.alive


def test_dead_browser_reconnects_via_factory():
    dead = _FakeBrowser()

    def boom(*a, **k):
        raise ConnectionError("browser gone")
    dead.navigate = boom
    healthy = _FakeBrowser()
    seq = iter([dead, healthy])
    ad = browser_mod._ADAPTER(browser_mod.PROFILE,
                              browser_factory=lambda: next(seq))
    inst = ad.launch(workdir=".")
    res = ad.invoke(inst, "navigate", url="https://x")
    assert res.ok and healthy.calls == [("navigate", "https://x")]


def test_factory_failure_reported_not_fake_dryrun():
    def bad_factory():
        raise ConnectionRefusedError("no cdp")
    ad = browser_mod._ADAPTER(browser_mod.PROFILE, browser_factory=bad_factory)
    inst = ad.launch(workdir=".")
    assert "cdp_connect_error" in inst.meta
    res = ad.invoke(inst, "navigate", url="https://x")
    assert not res.ok and "CDP 连接失败" in res.error
