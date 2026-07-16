"""通用应用适配层核心单测（级别① 纯逻辑，无需真机/GUI）。"""
from __future__ import annotations

import os

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
    assert {"kicad", "freecad", "jlceda", "notepad", "system"} <= set(reg.app_ids())
    for app_id in reg.app_ids():
        assert reg.describe_app(app_id)["verbs"], app_id


def test_system_profile_real_roundtrip(tmp_path):
    """整机底座（级别①）：exec/文件/列目录/进程/系统信息在本平台真跑真验（Linux/CI 即可）。"""
    reg = build_default_registry()
    mgr = SessionManager(reg, root=str(tmp_path))
    mgr.create("vm_sys")
    assert mgr.open_app("vm_sys", "system").ok

    # exec：真跑一行 shell，回显可读
    r = mgr.invoke("vm_sys", "system", "exec", cmd="echo 道法自然")
    assert r.ok and "道法自然" in r.value["stdout"]

    # 文件往返：写入→读回一致（自动建父目录）
    fpath = str(tmp_path / "sub" / "dao.txt")
    assert mgr.invoke("vm_sys", "system", "write_file", path=fpath, content="一生二").ok
    rr = mgr.invoke("vm_sys", "system", "read_file", path=fpath)
    assert rr.ok and rr.value["content"] == "一生二" and not rr.value["truncated"]

    # 列目录：至少含刚写的子目录
    ld = mgr.invoke("vm_sys", "system", "list_dir", path=str(tmp_path))
    assert ld.ok and any(e["name"] == "sub" and e["is_dir"] for e in ld.value["entries"])

    # 系统信息 + 进程列举
    si = mgr.invoke("vm_sys", "system", "sysinfo")
    assert si.ok and si.value["platform"] and si.value["home"]
    assert mgr.invoke("vm_sys", "system", "processes").ok

    # 环境变量：全量 + 单个
    assert isinstance(mgr.invoke("vm_sys", "system", "env").value, dict)


def test_system_backend_verbs(tmp_path):
    """后端控制面新动词：download 真跑（file://），Windows 专属动词跨平台参数校验与降级提示。"""
    import sys

    reg = build_default_registry()
    mgr = SessionManager(reg, root=str(tmp_path))
    mgr.create("vm_be")
    assert mgr.open_app("vm_be", "system").ok

    # download：file:// 真下载往返
    src = tmp_path / "src.bin"
    src.write_bytes(b"dao" * 100)
    dst = str(tmp_path / "dl" / "out.bin")
    dl = mgr.invoke("vm_be", "system", "download", url=src.as_uri(), path=dst)
    assert dl.ok and dl.value["bytes"] == 300
    assert open(dst, "rb").read() == b"dao" * 100
    # 参数缺失即拒
    assert not mgr.invoke("vm_be", "system", "download", url="", path=dst).ok

    # Windows 专属动词：非 Windows 明确降级提示；参数校验先于平台判断的动作校验
    for verb, kwargs in (
        ("install_pkg", {"pkg": "Git.Git"}),
        ("service", {"action": "list"}),
        ("registry", {"action": "read", "path": "HKCU\\Software\\Dao"}),
        ("schtask", {"action": "list"}),
    ):
        r = mgr.invoke("vm_be", "system", verb, **kwargs)
        if sys.platform == "win32":
            if verb == "install_pkg" and not r.ok and "winget" in (r.error or ""):
                continue  # 真机可能无 winget（如 Server/未装 App Installer）——降级信息已明确
            if verb == "registry" and not r.ok:
                # 真机 HKCU\Software\Dao 可能不存在：先写后读验证真往返
                assert mgr.invoke("vm_be", "system", "registry", action="write",
                                  path="HKCU\\Software\\Dao", name="probe", value="1").ok
                r = mgr.invoke("vm_be", "system", verb, **kwargs)
            assert r.ok, (verb, r.error)
        else:
            assert not r.ok and "Windows" in (r.error or "")
    # 非法 action 一律拒绝（平台无关）
    assert not mgr.invoke("vm_be", "system", "service", action="explode").ok
    assert not mgr.invoke("vm_be", "system", "registry", action="explode", path="HKCU\\X").ok
    assert not mgr.invoke("vm_be", "system", "schtask", action="explode").ok


def test_system_verbs_searchable_and_aliased():
    """整机动词可经中文/英文检索命中，且别名解析正确。"""
    reg = build_default_registry()
    hits = reg.search_verbs("执行命令 shell 运行")
    assert hits and hits[0]["app_id"] == "system" and hits[0]["verb"] == "exec"
    prof = reg.describe_app("system")
    names = {v["name"] for v in prof["verbs"]}
    assert {"exec", "read_file", "write_file", "list_dir", "processes", "env", "sysinfo"} <= names
    # 别名解析：cat→read_file、ls→list_dir、run→exec
    from core.profiles.builtin import system as sysmod
    assert sysmod.PROFILE.verb("cat").name == "read_file"
    assert sysmod.PROFILE.verb("ls").name == "list_dir"
    assert sysmod.PROFILE.verb("run").name == "exec"


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


def test_pcb_python_macro_does_not_shadow_pcbnew(tmp_path):
    """脚本落名不可为 _pcbnew.py/pcbnew.py：脚本目录在 sys.path 首位，会遮蔽 KiCad 原生模块。"""
    from core.profiles.builtin import kicad as kmod

    class FakeInstance:
        workdir = str(tmp_path)

    captured = {}

    class FakeAdapter:
        def run_cli(self, argv, instance, timeout=None):
            captured["argv"] = argv
            return None

    kmod._pcb_python(FakeAdapter(), FakeInstance(), script="print('x')")
    macro = captured["argv"][-1]
    assert os.path.basename(macro) not in ("_pcbnew.py", "pcbnew.py")
    assert os.path.exists(macro)


def test_search_verbs_finds_gerber():
    reg = build_default_registry()
    hits = reg.search_verbs("导出 gerber 制造文件")
    apps = {h["app_id"] for h in hits}
    assert "kicad" in apps or "jlceda" in apps
    assert hits[0]["score"] > 0


def test_run_cli_python_child_chinese_output(tmp_path):
    """run_cli 中文回环：非 UTF-8 码页 Windows 下 Python 子进程按区域码页写 stdout，
    回显非 Latin 文本即 UnicodeEncodeError 整条失败——需注入 UTF-8 子进程环境。"""
    import sys
    from core.adapter.subprocess_api import SubprocessApiAdapter
    from core.adapter.base import Instance

    prof = AppProfile(app_id="cli", display_name="CLI", level=AutomationLevel.API, verbs=[])
    adapter = SubprocessApiAdapter(prof)
    inst = Instance(app_id="cli", workdir=str(tmp_path))
    r = adapter.run_cli(
        [sys.executable, "-c", "import sys;sys.stdout.write(sys.argv[1])", "道法自然"],
        inst,
    )
    assert r.ok, r.error
    assert r.value["stdout"] == "道法自然"


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
    """级别②：无 driver 时返回结构化 UIA 动作计划，且每会话独立桌面隔离。

    本测验的是 dry-run 路径本身，故关闭实机 driver 自动探测（Windows 真机上否则会真执行）。"""
    reg = build_default_registry(autodetect_uia=False)
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


def test_uia_driver_plan_failure_propagates():
    """driver 回报 ok=False 时外层不得吞成成功（假成功防线）。"""
    def failing_driver(desktop, plan):
        return {"verb": plan["verb"], "ok": False,
                "results": [{"op": "find", "ok": False, "error": "未命中"}]}

    reg = build_default_registry(uia_driver=failing_driver)
    mgr = SessionManager(reg, root="/tmp/dao-win/test-uia-fail")
    mgr.create("vm_f")
    mgr.open_app("vm_f", "notepad")
    r = mgr.invoke("vm_f", "notepad", "type_text", text="x")
    assert not r.ok
    assert r.value["results"][0]["error"] == "未命中"


def test_vision_grounder_plan_failure_propagates():
    """grounder 回报 ok=False 时外层不得吞成成功（假成功防线）。"""
    reg = build_default_registry(
        vision_grounder=lambda d, p: {"verb": p["verb"], "ok": False, "results": []})
    mgr = SessionManager(reg, root="/tmp/dao-win/test-vis-fail")
    mgr.create("vm_g")
    mgr.open_app("vm_g", "mspaint")
    r = mgr.invoke("vm_g", "mspaint", "observe")
    assert not r.ok


def test_notepad_open_plan_carries_match_class():
    """打包应用(Win11 记事本)不吃 lpDesktop：open 计划须带 match_class 供 driver 兜底接管。"""
    reg = build_default_registry(autodetect_uia=False)
    mgr = SessionManager(reg, root="/tmp/dao-win/test-uia-mc")
    mgr.create("vm_mc")
    assert mgr.open_app("vm_mc", "notepad").ok
    r = mgr.invoke("vm_mc", "notepad", "open")
    assert r.ok
    step0 = r.value["plan"]["steps"][0]
    assert step0["op"] == "launch" and step0["match_class"] == "Notepad"


def test_osctl_binding_keeps_isolated_desktop_message_driver(monkeypatch):
    """agentctl 只绑定视觉兜底；级别② 必须保留跨隔离桌面可用的消息级 driver。"""
    seen = {}

    def message_driver(desktop, plan):
        seen["desktop"] = desktop
        return {"driver": "message", "verb": plan["verb"]}

    monkeypatch.setattr("core.adapter.uia_win.make_driver", lambda: message_driver)
    monkeypatch.setattr("core.adapter.osctl_driver.load_osctl", lambda: object())
    monkeypatch.setattr(
        "core.adapter.osctl_driver.make_grounder",
        lambda _osctl: lambda _desktop, _plan: {"x": 1, "y": 1},
    )

    reg = build_default_registry(bind_osctl=True)
    mgr = SessionManager(reg, root="/tmp/dao-win/test-osctl-isolation")
    mgr.create("vm_iso")
    mgr.open_app("vm_iso", "notepad")
    result = mgr.invoke("vm_iso", "notepad", "read_text")

    assert result.ok
    assert result.value == {"driver": "message", "verb": "read_text"}
    assert seen["desktop"] == "dao_vm_iso_notepad"


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


def test_win_desktop_name_sanitize_and_availability():
    """隔离桌面基石：名称规整去非法字符；非 Windows 平台 available()==False 且调用即报错。"""
    import sys

    from core.adapter import win_desktop

    # 桌面名不得含反斜杠/空格等（Win32 对象名约束）
    assert win_desktop.sanitize_name(r"dao\vm 1\notepad") == "dao_vm_1_notepad"
    assert win_desktop.sanitize_name("") == "dao_desktop"
    assert len(win_desktop.sanitize_name("x" * 300)) <= 96

    assert win_desktop.available() == (sys.platform == "win32")
    if sys.platform != "win32":
        # 非 Windows：占位实现调用即明确报错（引导上层退回 dry-run），import 无副作用
        import pytest

        with pytest.raises(RuntimeError):
            win_desktop.launch_on_desktop("dao_x", "notepad.exe")
        with pytest.raises(RuntimeError):
            win_desktop.enum_windows("dao_x")
        # 新增的消息级/取图基石在非 Windows 上同样占位报错（引导退回 dry-run）
        for fn in (win_desktop.list_children, win_desktop.find_edit_control,
                   win_desktop.send_chars, win_desktop.capture_window):
            with pytest.raises(RuntimeError):
                fn(0) if fn is not win_desktop.send_chars else fn(0, "x")


def test_win_desktop_edit_classes_present():
    """编辑区类名表须含 Win11 现代记事本(RichEditD2DPT)与经典 Edit（消息级往返标靶）。"""
    from core.adapter import win_desktop

    assert "RichEditD2DPT" in win_desktop._EDIT_CLASSES
    assert "Edit" in win_desktop._EDIT_CLASSES


def test_uia_win_driver_unavailable_off_windows():
    """级别② 实机 driver 在非 Windows/无隔离桌面能力时 available()==False、make_driver()==None。

    本源之路已改为纯 ctypes 消息级：available() 只取决于是否 Windows（无 pywinauto 依赖）。
    """
    import sys

    from core.adapter import uia_win

    assert uia_win.available() == (sys.platform == "win32")
    if sys.platform != "win32":
        assert uia_win.make_driver() is None


def test_uia_win_quote_helper():
    from core.adapter.uia_win import _quote

    assert _quote("notepad.exe") == "notepad.exe"
    assert _quote(r"C:\Program Files\x.exe") == r'"C:\Program Files\x.exe"'
    assert _quote('"already quoted"') == '"already quoted"'


def test_win_desktop_session_aware_launch_surface():
    """会话自适应起进程接口齐备：session0(SYSTEM)→用户令牌起隔离桌面进程，否则直起。

    这是"桥须跑在交互会话(WinSta0)"闭环的落地面——两个起进程原语都在，非 Windows 占位报错。
    """
    import sys

    from core.adapter import win_desktop

    assert hasattr(win_desktop, "launch_on_desktop")
    assert hasattr(win_desktop, "launch_on_desktop_as_user")
    if sys.platform != "win32":
        import pytest

        with pytest.raises(RuntimeError):
            win_desktop.launch_on_desktop_as_user("dao_x", "notepad.exe")


def test_uia_win_screenshot_path_softcoded(tmp_path, monkeypatch):
    """截图落盘目录软编码：显式 dir 优先，否则退系统临时目录——绝不硬编码 C:\\ 根。

    非提权交互会话写不了 C:\\ 根；此测直接驱动 _WinMsgDriver._screenshot（跨平台，
    monkeypatch 掉真窗口取图），校验默认落 tempfile.gettempdir()、显式 dir 覆盖生效。
    """
    import tempfile

    from core.adapter import uia_win

    drv = uia_win._WinMsgDriver()
    drv._top = 1234  # 假顶层窗口 hwnd，跳过 _await_top
    captured = {}
    monkeypatch.setattr(uia_win.win_desktop, "capture_window",
                        lambda hwnd, path: captured.setdefault("path", path) or path)

    # 默认：落系统临时目录，且不以盘符根硬编码
    r1 = drv._screenshot("dao_vmA_notepad", {})
    assert r1["screenshot"] and r1["screenshot"].startswith(tempfile.gettempdir())
    assert not r1["screenshot"].lower().startswith("c:\\dao")

    # 显式 dir 覆盖生效
    r2 = drv._screenshot("dao_vmA_notepad", {"dir": str(tmp_path)})
    assert r2["screenshot"].startswith(str(tmp_path))
    assert r2["screenshot"].endswith(".bmp")


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


def test_default_session_root_follows_system_tempdir(monkeypatch, tmp_path):
    import tempfile
    from core.session.manager import default_session_root
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    root = default_session_root()
    assert root == os.path.join(str(tmp_path), "dao-win", "sessions")
    reg = build_default_registry()
    mgr = SessionManager(reg)
    assert mgr.root == root
