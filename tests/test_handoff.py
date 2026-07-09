"""板块四 · 工程交接状态机 + 语义检索强化单测（纯逻辑，Linux/CI 即跑）。"""
from __future__ import annotations

import tempfile

from bridge.service import BridgeService
from core.agent.modes import ModeManager
from core.handoff import HandoffFlow
from core.profiles.builtin import build_default_registry


def _svc() -> BridgeService:
    tmp = tempfile.mkdtemp()
    reg = build_default_registry()
    return BridgeService(registry=reg, root=tmp + "/sessions",
                         modes=ModeManager(reg, state_path=tmp + "/mode.json"))


def test_create_validates_stages_and_ids():
    flow = HandoffFlow(build_default_registry(), root=tempfile.mkdtemp())
    assert "error" in flow.create("", "g", [{"app_id": "kicad"}])
    assert "error" in flow.create("p1", "g", [])
    bad = flow.create("p1", "g", [{"app_id": "不存在"}])
    assert "error" in bad and "未注册" in bad["error"]


def test_pipeline_advance_and_handoff_hints():
    flow = HandoffFlow(build_default_registry(), root=tempfile.mkdtemp())
    st = flow.create("watch", "智能手表全栈", [
        {"app_id": "kicad", "goal": "导出 gerber"},
        {"app_id": "freecad", "goal": "外壳建模导 STL"},
        {"goal": "整机打包交付"},
    ])
    assert st["status"] == "active"
    assert st["current"]["app_id"] == "kicad"
    assert st["handoff"]["handle"] == "@kicad"
    assert st["handoff"]["suggest_mode"] == "domain:kicad"

    st = flow.advance("watch", artifacts=["gerbers/F_Cu.gbr"], note="制造文件齐")
    assert st["current"]["app_id"] == "freecad"
    assert st["handoff"]["suggest_mode"] == "domain:freecad"
    assert st["stages"][0]["status"] == "done"
    assert st["stages"][0]["artifacts"] == ["gerbers/F_Cu.gbr"]

    st = flow.advance("watch", artifacts=["case.stl"])
    # 第三阶段无 app_id → 整机通用层
    assert st["current"]["app_id"] == ""
    assert st["handoff"]["suggest_mode"] == "windows"

    st = flow.advance("watch")
    assert st["status"] == "done"
    assert "完工" in st["handoff"]["summary"]
    assert "error" in flow.advance("watch")


def test_pipeline_persists_across_instances():
    root = tempfile.mkdtemp()
    reg = build_default_registry()
    HandoffFlow(reg, root=root).create("p", "g", [{"app_id": "kicad"}])
    st = HandoffFlow(reg, root=root).status("p")
    assert st["current"]["app_id"] == "kicad"


def test_bridge_project_endpoints():
    svc = _svc()
    st, body = svc.dispatch("POST", "/api/project.create", {
        "project_id": "e2e", "goal": "PCB→3D",
        "stages": [{"app_id": "kicad", "goal": "gerber"},
                   {"app_id": "freecad", "goal": "stl"}],
    })
    assert st == 200 and body["current"]["app_id"] == "kicad"
    st, body = svc.dispatch("POST", "/api/project.advance",
                            {"project_id": "e2e", "artifacts": ["a.gbr"]})
    assert st == 200 and body["current"]["app_id"] == "freecad"
    st, body = svc.dispatch("GET", "/api/project.list")
    assert st == 200 and body["projects"][0]["project_id"] == "e2e"
    st, body = svc.dispatch("POST", "/api/project.status", {"project_id": "e2e"})
    assert st == 200 and body["handoff"]["handle"] == "@freecad"


def test_active_project_injected_into_session_prompt():
    svc = _svc()
    svc.dispatch("POST", "/api/session.create", {"session_id": "s1"})
    _, before = svc.dispatch("POST", "/api/session.prompt", {"session_id": "s1"})
    assert "进行中的跨领域工程" not in before["prompt"]
    svc.dispatch("POST", "/api/project.create", {
        "project_id": "pj", "goal": "PCB→3D",
        "stages": [{"app_id": "kicad", "goal": "gerber"}]})
    _, after = svc.dispatch("POST", "/api/session.prompt", {"session_id": "s1"})
    assert "进行中的跨领域工程" in after["prompt"]
    assert "@kicad" in after["prompt"] and "第 1/1 环节" in after["prompt"]
    # coding 模式（机控面关闭）不注入
    svc.dispatch("POST", "/api/mode.set", {"mode": "coding"})
    _, coding = svc.dispatch("POST", "/api/session.prompt", {"session_id": "s1"})
    assert "进行中的跨领域工程" not in coding["prompt"]


def test_search_verbs_semantic_bridge():
    reg = build_default_registry()
    # 纯中文查询经同义桥命中英文动词名
    hits = reg.search_verbs("导出制造文件")
    assert any(h["verb"] == "export_gerbers" for h in hits[:3])
    hits = reg.search_verbs("3D建模 网格导出")
    assert any(h["app_id"] == "freecad" for h in hits[:3])
    # 别名直命中显著加权
    hits = reg.search_verbs("检查 模型树")
    assert any(h["app_id"] == "freecad" and "inspect" in h["verb"] for h in hits[:3])
