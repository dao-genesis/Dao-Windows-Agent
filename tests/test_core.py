"""通用应用适配层核心单测（级别① 纯逻辑，无需真机/GUI）。"""
from __future__ import annotations

from core.adapter.base import ActionResult, AppAdapter, Instance
from core.agent.rule import build_system_prompt
from core.profiles.builtin import build_default_registry
from core.profiles.schema import AppProfile, AutomationLevel, Verb
from core.session.manager import SessionManager


def _fake_registry(tmp_verb_handler):
    from core.profiles.registry import ProfileRegistry

    class FakeAdapter(AppAdapter):
        level = AutomationLevel.API

        def launch(self, workdir, **kw):
            return Instance(app_id=self.profile.app_id, workdir=workdir)

        def invoke(self, instance, verb, **params):
            v = self.profile.verb(verb)
            if v is None:
                return ActionResult.bad("unknown verb")
            return ActionResult.good(v.handler(instance, **params))

        def shutdown(self, instance):
            instance.alive = False

    prof = AppProfile(
        app_id="fake", display_name="Fake", level=AutomationLevel.API,
        verbs=[Verb("echo", "回显", {"msg": "文本"}, handler=tmp_verb_handler)],
    )
    reg = ProfileRegistry()
    reg.register(prof, lambda p: FakeAdapter(p))
    return reg


def test_registry_builtin_loads():
    reg = build_default_registry()
    assert {"kicad", "freecad", "jlceda", "notepad"} <= set(reg.app_ids())
    for app_id in reg.app_ids():
        assert reg.describe_app(app_id)["verbs"], app_id


def test_deepened_profile_verbs_present():
    reg = build_default_registry()
    kicad = {v["name"] for v in reg.describe_app("kicad")["verbs"]}
    assert {"export_bom", "export_netlist", "export_sch_pdf",
            "export_pcb_svg", "pcb_python"} <= kicad
    freecad = {v["name"] for v in reg.describe_app("freecad")["verbs"]}
    assert {"export_iges", "export_brep", "inspect_doc"} <= freecad


def test_search_verbs_finds_deepened_verbs():
    reg = build_default_registry()
    assert reg.search_verbs("导出 BOM 物料清单")[0]["verb"] == "export_bom"
    hits = reg.search_verbs("pcbnew python script")
    assert hits and hits[0]["app_id"] == "kicad" and hits[0]["verb"] == "pcb_python"
    hits = reg.search_verbs("inspect model tree")
    assert hits and hits[0]["verb"] == "inspect_doc"


def test_search_verbs_finds_gerber():
    reg = build_default_registry()
    hits = reg.search_verbs("导出 gerber 制造文件")
    apps = {h["app_id"] for h in hits}
    assert "kicad" in apps or "jlceda" in apps
    assert hits[0]["score"] > 0


def test_profile_validation_rejects_dupes():
    from core.profiles.registry import ProfileRegistry
    bad = AppProfile(app_id="x", display_name="X", level=AutomationLevel.API,
                     verbs=[Verb("a", "", handler=lambda *a, **k: 1),
                            Verb("b", "", aliases=("a",), handler=lambda *a, **k: 1)])
    try:
        ProfileRegistry().register(bad, lambda p: None)
        assert False, "应因动词名冲突报错"
    except ValueError as e:
        assert "冲突" in str(e)


def test_session_lifecycle_and_isolation(tmp_path):
    reg = _fake_registry(lambda instance, msg="hi": f"{instance.app_id}:{msg}")
    mgr = SessionManager(reg, root=str(tmp_path))
    s1 = mgr.create("vm_a")
    s2 = mgr.create("vm_b")
    assert set(mgr.list()) == {"vm_a", "vm_b"}
    assert mgr.open_app("vm_a", "fake").ok
    assert mgr.open_app("vm_b", "fake").ok
    # 两会话工作目录隔离
    assert s1.instances["fake"].workdir != s2.instances["fake"].workdir
    r = mgr.invoke("vm_a", "fake", "echo", msg="道")
    assert r.ok and r.value == "fake:道"
    # 未打开的软件应报错
    assert not mgr.invoke("vm_a", "nope", "echo").ok
    # 销毁隔离：销毁 a 不影响 b
    assert mgr.destroy("vm_a").ok
    assert "vm_a" not in mgr.list() and "vm_b" in mgr.list()
    assert mgr.invoke("vm_b", "fake", "echo", msg="x").ok


def test_uia_desktop_dry_run_builds_plan():
    """级别②：无 driver 时返回结构化 UIA 动作计划，且每会话独立桌面隔离。"""
    reg = build_default_registry()
    mgr = SessionManager(reg, root="/tmp/dao-win/test-uia")
    mgr.create("vm_np1")
    mgr.create("vm_np2")
    assert mgr.open_app("vm_np1", "notepad").ok
    assert mgr.open_app("vm_np2", "notepad").ok

    r = mgr.invoke("vm_np1", "notepad", "type_text", text="道法自然")
    assert r.ok and r.value["dry_run"]
    assert r.value["desktop"] == "dao_vm_np1_notepad"
    steps = r.value["plan"]["steps"]
    assert steps[-1]["op"] == "set_value" and steps[-1]["text"] == "道法自然"

    # 两会话桌面名不同 → 隔离并行
    r2 = mgr.invoke("vm_np2", "notepad", "read_text")
    assert r2.value["desktop"] == "dao_vm_np2_notepad"


def test_uia_driver_binding_executes_plan():
    """注入 driver 后级别② 不再 dry-run，而是把动作计划交 driver 执行。"""
    seen = {}

    def fake_driver(desktop, plan):
        seen["desktop"] = desktop
        return {"ran": plan["verb"], "steps": len(plan["steps"])}

    reg = build_default_registry(uia_driver=fake_driver)
    mgr = SessionManager(reg, root="/tmp/dao-win/test-uia-drv")
    mgr.create("vm_d")
    mgr.open_app("vm_d", "notepad")
    r = mgr.invoke("vm_d", "notepad", "type_text", text="行于大道")
    assert r.ok and r.value == {"ran": "type_text", "steps": 2}
    assert seen["desktop"] == "dao_vm_d_notepad"


def test_vision_dry_run_and_grounder_binding():
    """级别③：dry-run 产出视觉计划；注入 grounder 后交其执行；非法 op 拒绝。"""
    reg = build_default_registry()
    mgr = SessionManager(reg, root="/tmp/dao-win/test-vis")
    mgr.create("vm_v")
    assert mgr.open_app("vm_v", "mspaint").ok
    r = mgr.invoke("vm_v", "mspaint", "pick_tool", tool="铅笔")
    assert r.ok and r.value["dry_run"] and r.value["desktop"] == "dao_vm_v_mspaint"
    assert r.value["plan"]["steps"][-1]["op"] == "click_hint"
    assert "铅笔" in r.value["plan"]["steps"][-1]["target_hint"]

    reg2 = build_default_registry(vision_grounder=lambda d, p: {"ran": p["verb"], "on": d})
    mgr2 = SessionManager(reg2, root="/tmp/dao-win/test-vis2")
    mgr2.create("vm_v2")
    mgr2.open_app("vm_v2", "mspaint")
    r2 = mgr2.invoke("vm_v2", "mspaint", "observe")
    assert r2.ok and r2.value == {"ran": "observe", "on": "dao_vm_v2_mspaint"}

    from core.adapter.vision import VisionAdapter
    from core.profiles.builtin import mspaint
    try:
        VisionAdapter(mspaint.PROFILE).build_plan("x", [{"op": "teleport"}])
    except ValueError as e:
        assert "非法 vision op" in str(e)
    else:
        raise AssertionError("应拒绝非法 op")


def test_search_verbs_pure_chinese_queries():
    """纯中文查询（本项目主语言）须能命中动词：CJK 单字+二元词元化。"""
    reg = build_default_registry()
    assert reg.search_verbs("在记事本里写文字")[0]["verb"] == "type_text"
    assert reg.search_verbs("读取记事本内容")[0]["verb"] == "read_text"
    hits = reg.search_verbs("画布上画一笔")
    assert hits[0]["app_id"] == "mspaint" and hits[0]["verb"] == "stroke"
    assert reg.search_verbs("选择铅笔工具")[0]["verb"] == "pick_tool"


def test_uia_build_plan_rejects_bad_op():
    from core.adapter.uia_desktop import UiaDesktopAdapter
    from core.profiles.builtin import notepad

    adapter = UiaDesktopAdapter(notepad.PROFILE)
    try:
        adapter.build_plan("x", [{"op": "teleport"}])
    except ValueError as e:
        assert "非法 UIA op" in str(e)
    else:
        raise AssertionError("应拒绝非法 op")


def test_cdp_dry_run_builds_js():
    reg = build_default_registry()
    mgr = SessionManager(reg, root="/tmp/dao-win/test-cdp")
    mgr.create("vm_c")
    mgr.open_app("vm_c", "jlceda")
    r = mgr.invoke("vm_c", "jlceda", "api_namespaces")
    assert r.ok and "_EXTAPI_ROOT_" in r.value["js"]


def test_system_prompt_includes_open_apps():
    reg = build_default_registry()
    prompt = build_system_prompt(reg, ["kicad", "jlceda"])
    assert "KiCad" in prompt and "嘉立创EDA" in prompt and "无为而无不为" in prompt
