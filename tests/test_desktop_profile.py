"""整机 GUI 画像（AI GUI 体系收编 · @gui）单测：注册/词表/计划翻译/dry-run/实调。"""
from __future__ import annotations

import pytest

from core.adapter.gui_desktop import DESKTOP_OPS, GuiDesktopAdapter
from core.adapter.osctl_driver import OsctlExecutor
from core.profiles.builtin import build_default_registry
from core.profiles.builtin import desktop as desktop_profile
from core.session.manager import SessionManager
from tests.test_osctl_driver import PcOsctl


def _mgr(tmp_path, executor=None):
    reg = build_default_registry(autodetect_uia=False, vision_grounder=executor)
    return SessionManager(reg, root=str(tmp_path))


def test_registry_contains_desktop_universal_layer(tmp_path):
    reg = build_default_registry(autodetect_uia=False)
    prof = reg.get("desktop")
    assert prof is not None and prof.layer == "universal" and prof.handle == "gui"
    assert not prof.validate()


def test_dry_run_plans_offline(tmp_path):
    mgr = _mgr(tmp_path)
    mgr.create("s1")
    mgr.open_app("s1", "desktop")
    r = mgr.invoke("s1", "desktop", "ui_tree", title="记事本", depth=2)
    assert r.ok and r.value["dry_run"] is True
    ops = [s["op"] for s in r.value["plan"]["steps"]]
    assert ops == ["activate", "tree"]
    r2 = mgr.invoke("s1", "desktop", "click", x=10, y=20)
    assert r2.ok and r2.value["plan"]["steps"][0]["op"] == "click_xy"


def test_all_verbs_build_legal_plans(tmp_path):
    mgr = _mgr(tmp_path)
    mgr.create("s2")
    mgr.open_app("s2", "desktop")
    cases = {
        "observe": {},
        "screenshot": {"path": "C:/t.png"},
        "windows": {},
        "activate": {"title": "记事本"},
        "click": {"x": 1, "y": 2},
        "move": {"x": 1, "y": 2},
        "drag": {"x1": 0, "y1": 0, "x2": 9, "y2": 9},
        "scroll": {"dy": -3},
        "type": {"text": "道"},
        "keys": {"keys": "^s"},
        "clipboard_get": {},
        "clipboard_set": {"text": "无为"},
        "ui_tree": {"title": "记事本"},
        "find": {"title": "记事本", "name": "保存"},
        "click_hint": {"hint": "确定按钮", "title": "对话框"},
        "type_hint": {"hint": "输入框", "text": "道", "title": "记事本"},
        "region_hash": {"x": 0, "y": 0, "w": 8, "h": 8},
        "wait_change": {"timeout": 1},
    }
    for verb, params in cases.items():
        r = mgr.invoke("s2", "desktop", verb, **params)
        assert r.ok, f"{verb}: {r.error}"
        for s in r.value["plan"]["steps"]:
            assert s["op"] in DESKTOP_OPS


def test_build_plan_rejects_illegal_op():
    with pytest.raises(ValueError):
        GuiDesktopAdapter.build_plan("v", [{"op": "launch", "exe": "x"}])


def test_executor_bound_runs_real_calls(tmp_path):
    fake = PcOsctl(windows=[{"id": 3, "title": "画图"}])
    ex = OsctlExecutor(fake)
    mgr = _mgr(tmp_path, executor=ex.run)
    mgr.create("s3")
    mgr.open_app("s3", "desktop")
    r = mgr.invoke("s3", "desktop", "activate", title="画图")
    assert r.ok and ("activate_window", 3) in fake.calls
    r2 = mgr.invoke("s3", "desktop", "clipboard_set", text="道法自然")
    assert r2.ok and fake.clip == "道法自然"
    # 未命中窗口如实失败（错误穿透 ActionResult）
    r3 = mgr.invoke("s3", "desktop", "activate", title="不存在")
    assert not r3.ok


def test_profile_prompt_declares_semantic_first():
    assert "语义优先" in desktop_profile.PROFILE.prompt_snippet
