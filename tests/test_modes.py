"""模式切换层单测（纯逻辑，Linux/CI 即跑）。"""
from __future__ import annotations

import json

from bridge.service import BridgeService
from core.agent.modes import DEFAULT_MODE, ModeManager
from core.profiles.builtin import build_default_registry


def _mm(tmp_path) -> ModeManager:
    return ModeManager(build_default_registry(), state_path=str(tmp_path / "mode.json"))


def test_builtin_and_domain_modes_enumerated(tmp_path):
    mm = _mm(tmp_path)
    ids = [m.mode_id for m in mm.modes()]
    assert ids[:3] == ["primary", "coding", "windows"]
    assert "domain:kicad" in ids and "domain:freecad" in ids
    assert "domain:system" not in ids  # 通用层不生成专精模式


def test_default_mode_and_set_persists(tmp_path):
    mm = _mm(tmp_path)
    assert mm.current.mode_id == DEFAULT_MODE
    mm.set("windows")
    with open(mm.state_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["mode"] == "windows" and data["replace_official"] is True
    # 新实例从契约文件恢复当前模式
    mm2 = ModeManager(build_default_registry(), state_path=mm.state_path)
    assert mm2.current.mode_id == "windows"


def test_set_unknown_mode_raises(tmp_path):
    mm = _mm(tmp_path)
    try:
        mm.set("nope")
        raise AssertionError("应当抛 ValueError")
    except ValueError as exc:
        assert "无此模式" in str(exc)


def test_tool_policy_slices_apps(tmp_path):
    mm = _mm(tmp_path)
    all_apps = set(mm.registry.app_ids())
    assert set(mm.allowed_apps()) == all_apps  # primary=all
    mm.set("coding")
    assert mm.allowed_apps() == []
    mm.set("domain:kicad")
    allowed = set(mm.allowed_apps())
    assert "kicad" in allowed and "system" in allowed
    assert "freecad" not in allowed


def test_capabilities_and_prompt_follow_mode(tmp_path):
    mm = _mm(tmp_path)
    mm.set("domain:freecad")
    caps = mm.capabilities()
    assert caps["mode"]["mode_id"] == "domain:freecad"
    assert [d["app_id"] for d in caps["domains"]] == ["freecad"]
    prompt = mm.build_prompt(["freecad"])
    assert "专精模式" in prompt and "本源纪律" in prompt
    mm.set("coding")
    assert "机控面已整体关闭" in mm.build_prompt([])
    assert "本源纪律" not in mm.build_prompt([])


def test_dispatch_snippet_in_all_policy_prompts(tmp_path):
    mm = _mm(tmp_path)
    prompt = mm.build_prompt([])
    assert "可自主调度的领域模块" in prompt and "@kicad" in prompt
    mm.set("domain:kicad")
    assert "可自主调度的领域模块" not in mm.build_prompt([])


def test_bridge_mode_endpoints(tmp_path):
    reg = build_default_registry()
    svc = BridgeService(
        registry=reg,
        root=str(tmp_path / "sessions"),
        modes=ModeManager(reg, state_path=str(tmp_path / "mode.json")),
    )
    status, body = svc.dispatch("GET", "/api/mode.list")
    assert status == 200 and body["current"] == DEFAULT_MODE
    status, body = svc.dispatch("POST", "/api/mode.set", {"mode": "domain:kicad"})
    assert status == 200 and body["current"]["mode_id"] == "domain:kicad"
    status, body = svc.dispatch("GET", "/api/mode.get")
    assert status == 200 and "kicad" in body["allowed_apps"]
    status, body = svc.dispatch("GET", "/api/capabilities")
    assert status == 200 and body["mode"]["mode_id"] == "domain:kicad"
    status, body = svc.dispatch("POST", "/api/mode.set", {"mode": "nope"})
    assert status == 200 and "无此模式" in body["error"]
    status, body = svc.dispatch("POST", "/api/session.create", {"session_id": "s1"})
    assert status == 200
    status, body = svc.dispatch("POST", "/api/session.prompt", {"session_id": "s1"})
    assert status == 200 and body["mode"] == "domain:kicad"
    assert "专精模式" in body["prompt"]
