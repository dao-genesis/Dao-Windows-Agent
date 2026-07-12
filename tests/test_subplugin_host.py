"""板块三 · 子插件宿主真实对接单测（真 HTTP 端点 + 发现收编 + 桥端调用）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile

from bridge.service import BridgeService
from bridge.subplugin_host import SubpluginHost, _render_shell, load_spec
from core.agent.modes import ModeManager
from core.profiles.builtin import build_default_registry
from core.subplugin import register_subplugins

_SPEC = {
    "app_id": "echo-ext",
    "display_name": "Echo (子插件实例)",
    "mention": "echo",
    "token": "t0ken",
    "verbs": [
        # 跨平台 shell 模板：真机（Linux/Windows）都能真跑真验
        {"name": "say", "summary": "回显文本", "params": {"text": "文本"},
         "aliases": ["回显"],
         "shell": f'"{sys.executable}" -c "import sys;sys.stdout.write(sys.argv[1])" {{text}}'},
        {"name": "fail", "summary": "必败动词",
         "shell": f'"{sys.executable}" -c "import sys;sys.exit(1)"'},
        {"name": "py", "summary": "进程内 handler"},
    ],
}


def _up(spec: dict) -> SubpluginHost:
    host = SubpluginHost(dict(spec, verbs=[dict(v) for v in spec["verbs"]]))
    host.start()
    return host


def test_render_shell_quotes_params():
    cmd = _render_shell("printf %s {text}", {"text": "a; rm -rf /"})
    expected = '"a; rm -rf /"' if os.name == "nt" else "'a; rm -rf /'"
    assert expected in cmd
    assert _render_shell("x {missing}", {}) == "x "


def test_host_real_http_invoke_and_auth():
    host = _up(_SPEC)
    try:
        import urllib.request

        def call(verb, params, token="t0ken"):
            req = urllib.request.Request(
                host.invoke_url,
                data=json.dumps({"verb": verb, "params": params}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + token})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:  # noqa: PERF203
                return e.code, json.loads(e.read())

        st, body = call("say", {"text": "道法自然"})
        assert st == 200 and body["ok"] and body["value"] == "道法自然"
        st, body = call("fail", {})
        assert st == 200 and not body["ok"]
        st, body = call("say", {"text": "x"}, token="wrong")
        assert st == 401
        st, body = call("nope", {})
        assert not body["ok"] and "未知动词" in body["error"]
    finally:
        host.stop()


def test_host_python_handler_and_descriptor_shape():
    host = _up(_SPEC)
    host.register_handler("py", lambda **kw: {"got": kw})
    try:
        desc = host.descriptor()
        assert desc["invoke_url"] == host.invoke_url
        assert desc["layer"] == "domain"
        assert all("shell" not in v for v in desc["verbs"])  # 执行面不外泄
        assert host._invoke("py", {"a": 1}, "") == {"ok": True, "value": {"got": {"a": 1}}}
    finally:
        host.stop()


def test_end_to_end_discovery_and_bridge_invoke():
    """真链路：宿主起端点 → 写描述符 → registry 收编 → 桥按模式 invoke。"""
    host = _up(_SPEC)
    tmp = tempfile.mkdtemp()
    try:
        ddir = os.path.join(tmp, "subplugins")
        host.write_descriptor(ddir)
        reg = build_default_registry()
        got = register_subplugins(reg, discovery_dir=ddir)
        assert got == ["echo-ext"]
        svc = BridgeService(registry=reg, root=tmp + "/sessions",
                            modes=ModeManager(reg, state_path=tmp + "/mode.json"))
        svc.dispatch("POST", "/api/mode.set", {"mode": "domain:echo-ext"})
        svc.dispatch("POST", "/api/session.create", {"session_id": "s1"})
        svc.dispatch("POST", "/api/session.open_app",
                     {"session_id": "s1", "app_id": "echo-ext"})
        st, body = svc.dispatch("POST", "/api/session.invoke", {
            "session_id": "s1", "app_id": "echo-ext",
            "verb": "say", "params": {"text": "无为而无不为"}})
        assert st == 200 and body["ok"] and body["value"] == "无为而无不为"
        # @ 调度也认得这路子插件
        st, body = svc.dispatch("POST", "/api/route", {"text": "@echo 回显 文本"})
        assert body["layer"] == "domain" and body["targets"] == ["echo-ext"]
    finally:
        host.stop()


def test_shipped_specs_are_loadable():
    root = os.path.join(os.path.dirname(__file__), "..", "bridge", "subplugin_specs")
    specs = [f for f in os.listdir(root) if f.endswith(".json")]
    assert specs
    for name in specs:
        host = SubpluginHost(load_spec(os.path.join(root, name)))
        desc = host.descriptor()
        assert desc["app_id"] and desc["verbs"]
        host.stop()


def test_shell_templates_are_cross_platform():
    """shell 模板经 subprocess(shell=True) 执行：Windows 下是 cmd.exe，
    bash 专属语法(${VAR:-default}) 会被当成非法路径。真机冷启动实测踩坑——
    guest 内 HA states 曾报「filename/directory syntax incorrect」即此因。
    源级护栏：禁止在随盘 spec 的 shell 模板里出现 bash 默认值展开。"""
    import re
    root = os.path.join(os.path.dirname(__file__), "..", "bridge", "subplugin_specs")
    bashism = re.compile(r"\$\{\{?\w+:-")  # ${VAR:-x} 或 format 转义后的 ${{VAR:-x}}
    for name in os.listdir(root):
        if not name.endswith(".json"):
            continue
        spec = load_spec(os.path.join(root, name))
        for verb in spec.get("verbs", []):
            tmpl = verb.get("shell")
            if tmpl:
                assert not bashism.search(tmpl), (
                    f"{name}:{verb['name']} shell 模板含 bash 专属语法，"
                    f"Windows cmd.exe 无法解析: {tmpl}")
