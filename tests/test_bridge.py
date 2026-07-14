"""机控桥（bridge/）单测：REST dispatch 纯函数 + MCP 外壳，均无 socket、无第三方依赖。"""
from __future__ import annotations

import json

from bridge.mcp import handle_request
from bridge.service import BridgeService


def _svc(tmp_path):
    return BridgeService(root=str(tmp_path))


def test_dispatch_health_and_apps(tmp_path):
    svc = _svc(tmp_path)
    status, obj = svc.dispatch("GET", "/api/health")
    assert status == 200 and obj["ok"] and {"kicad", "freecad", "jlceda", "notepad"} <= set(obj["apps"])
    status, obj = svc.dispatch("GET", "/api/apps")
    assert status == 200 and "kicad" in obj["apps"]


def test_dispatch_session_full_lifecycle(tmp_path):
    svc = _svc(tmp_path)
    status, created = svc.dispatch("POST", "/api/session.create", {"session_id": "vm1"})
    assert status == 200 and created["session_id"] == "vm1"

    status, opened = svc.dispatch("POST", "/api/session.open_app",
                                  {"session_id": "vm1", "app_id": "jlceda"})
    assert status == 200 and opened["ok"]

    status, listed = svc.dispatch("GET", "/api/session.list")
    assert status == 200 and listed["sessions"] == [{"session_id": "vm1", "apps": ["jlceda"]}]

    status, invoked = svc.dispatch("POST", "/api/session.invoke",
                                   {"session_id": "vm1", "app_id": "jlceda",
                                    "verb": "api_namespaces"})
    assert status == 200 and invoked["ok"] and "_EXTAPI_ROOT_" in invoked["value"]["js"]

    status, prompt = svc.dispatch("POST", "/api/session.prompt", {"session_id": "vm1"})
    assert status == 200 and "嘉立创" in prompt["prompt"]

    status, destroyed = svc.dispatch("POST", "/api/session.destroy", {"session_id": "vm1"})
    assert status == 200 and destroyed["ok"]


def test_dispatch_discovery_and_errors(tmp_path):
    svc = _svc(tmp_path)
    status, hits = svc.dispatch("POST", "/api/search_verbs", {"query": "导出 gerber"})
    assert status == 200 and hits["hits"]

    status, desc = svc.dispatch("POST", "/api/describe_app", {"app_id": "kicad"})
    assert status == 200 and desc["app_id"] == "kicad" and desc["verbs"]

    status, obj = svc.dispatch("POST", "/api/describe_app", {})
    assert status == 400 and "app_id" in obj["error"]

    status, obj = svc.dispatch("GET", "/api/nope")
    assert status == 404

    status, obj = svc.dispatch("POST", "/api/session.invoke",
                               {"session_id": "ghost", "app_id": "kicad", "verb": "version"})
    assert status == 200 and not obj["ok"] and "会话不存在" in obj["error"]


def test_dispatch_route_universal_and_domain(tmp_path):
    svc = _svc(tmp_path)
    # 无 @ → 整机通用层
    status, d = svc.dispatch("POST", "/api/route", {"text": "列出正在运行的进程"})
    assert status == 200 and d["layer"] == "universal" and d["targets"] == ["browser", "desktop", "system"]
    # @kicad → 领域工作层，动词候选仅限目标层
    status, d = svc.dispatch("POST", "/api/route", {"text": "@kicad 导出 gerber"})
    assert status == 200 and d["layer"] == "domain" and d["targets"] == ["kicad"]
    assert d["verb_hints"] and all(h["app_id"] == "kicad" for h in d["verb_hints"])
    # 未注册句柄如实回报，不臆造
    status, d = svc.dispatch("POST", "/api/route", {"text": "@notexist 干点啥"})
    assert status == 200 and "notexist" in d["unresolved"] and d["layer"] == "universal"
    # 缺参
    status, obj = svc.dispatch("POST", "/api/route", {})
    assert status == 400 and "text" in obj["error"]


def test_dispatch_capabilities(tmp_path):
    svc = _svc(tmp_path)
    status, cap = svc.dispatch("GET", "/api/capabilities")
    assert status == 200
    handles = {e["handle"] for e in cap["universal"] + cap["domains"]}
    assert "@win" in handles and "@kicad" in handles
    assert any(e["app_id"] == "system" for e in cap["universal"])


def test_mcp_route_and_capabilities_tools():
    resp = handle_request({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"route", "capabilities"} <= names

    resp = handle_request({"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                           "params": {"name": "route",
                                      "arguments": {"text": "@freecad 导出 STEP"}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["layer"] == "domain" and payload["targets"] == ["freecad"]


def test_installed_subplugin_becomes_routable(tmp_path, monkeypatch):
    """插件收编的领域子插件描述符 → 机控桥自动发现 → @句柄可路由（端到端·纯逻辑）。"""
    spdir = tmp_path / "subplugins"
    spdir.mkdir()
    (spdir / "freecad-ext.json").write_text(json.dumps({
        "app_id": "freecad-ext", "display_name": "FreeCAD (3D·子插件)",
        "mention": "freecad3d", "layer": "domain", "level": 1,
        "invoke_url": "http://127.0.0.1:18920/invoke",
        "verbs": [{"name": "export_step", "summary": "导出 STEP", "aliases": ["step"]}],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("DAO_SUBPLUGIN_DIR", str(spdir))

    svc = BridgeService(root=str(tmp_path))
    status, apps = svc.dispatch("GET", "/api/apps")
    assert status == 200 and "freecad-ext" in apps["apps"]

    status, d = svc.dispatch("POST", "/api/route", {"text": "@freecad3d 导出 STEP"})
    assert status == 200 and d["layer"] == "domain" and d["targets"] == ["freecad-ext"]

    status, cap = svc.dispatch("GET", "/api/capabilities")
    assert any(e["handle"] == "@freecad3d" and e["origin"] == "external"
               for e in cap["domains"])


def test_mcp_initialize_and_tools_list():
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["result"]["serverInfo"]["name"] == "dao-windows-agent-bridge"

    resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"search_verbs", "describe_app", "session_create",
            "session_open_app", "session_invoke", "session_destroy"} <= names


def test_mcp_tool_call_roundtrip():
    resp = handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": "session_create",
                                      "arguments": {"session_id": "mcp_vm"}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["session_id"] == "mcp_vm" and not resp["result"]["isError"]

    resp = handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                           "params": {"name": "search_verbs",
                                      "arguments": {"query": "导出 STEP 模型"}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["hits"]

    resp = handle_request({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                           "params": {"name": "nope", "arguments": {}}})
    assert resp["result"]["isError"]

    # 通知（无 id）不回包
    assert handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_mcp_mode_and_project_tools():
    """三插件融合枢纽（模式切换）与工程交接须经 MCP 外壳可达（Cascade/Devin 原生调度面）。"""
    resp = handle_request({"jsonrpc": "2.0", "id": 20, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"mode_list", "mode_get", "mode_set",
            "project_create", "project_advance", "project_status", "project_list"} <= names

    resp = handle_request({"jsonrpc": "2.0", "id": 21, "method": "tools/call",
                           "params": {"name": "mode_list", "arguments": {}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    mode_ids = {m["mode_id"] for m in payload["modes"]}
    assert {"primary", "coding", "windows", "native"} <= mode_ids
    assert payload["current"] in mode_ids

    # 切到当前模式（幂等·不扰动持久态）也应闭环成功
    resp = handle_request({"jsonrpc": "2.0", "id": 22, "method": "tools/call",
                           "params": {"name": "mode_set",
                                      "arguments": {"mode": payload["current"]}}})
    out = json.loads(resp["result"]["content"][0]["text"])
    assert out["current"]["mode_id"] == payload["current"] and out["allowed_apps"] is not None

    resp = handle_request({"jsonrpc": "2.0", "id": 23, "method": "tools/call",
                           "params": {"name": "project_list", "arguments": {}}})
    assert not resp["result"]["isError"]
    resp = handle_request({"jsonrpc": "2.0", "id": 24, "method": "tools/call",
                           "params": {"name": "project_status",
                                      "arguments": {"project_id": "_no_such_project_"}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload.get("error")


def test_mcp_handler_exception_returns_error_not_crash():
    from bridge import mcp as _mcp
    _mcp._TOOLS["_boom"] = {"description": "x", "properties": {}, "required": [],
                            "handler": lambda a: (_ for _ in ()).throw(RuntimeError("炸"))}
    try:
        resp = handle_request({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                               "params": {"name": "_boom", "arguments": {}}})
        assert resp["result"]["isError"]
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert "RuntimeError" in payload["error"]
    finally:
        del _mcp._TOOLS["_boom"]
