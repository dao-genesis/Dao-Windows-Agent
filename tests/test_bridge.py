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
    assert status == 200 and obj["ok"] and set(obj["apps"]) == {"kicad", "freecad", "jlceda"}
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
