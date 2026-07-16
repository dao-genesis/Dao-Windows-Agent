"""BridgeService 分身治理 + 宏沉淀 REST/MCP 全链路单测（REST 与 MCP 共享同一份态）。"""
from __future__ import annotations

import json

from bridge.mcp import _TOOL_GROUPS, _TOOLS, handle_request
from bridge.service import BridgeService
from core.macros import MacroStore


def _svc(tmp_path) -> BridgeService:
    return BridgeService(root=str(tmp_path / "sessions"),
                         macros=MacroStore(path=str(tmp_path / "macros.json")))


def _call(svc, name, args):
    r = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": args}}, service=svc)
    return json.loads(r["result"]["content"][0]["text"]), r["result"]["isError"]


def test_clone_lifecycle_rest_routes(tmp_path):
    svc = _svc(tmp_path)
    code, body = svc.dispatch("POST", "/api/clone.register",
                              {"clone_id": "s2", "app_id": "vscode", "tier": "desktop"})
    assert code == 200 and body["state"] == "alive"
    code, body = svc.dispatch("POST", "/api/clone.heartbeat", {"clone_id": "s2"})
    assert code == 200 and body["beats"] == 2
    code, body = svc.dispatch("GET", "/api/clone.health", {})
    assert code == 200 and body["total"] == 1 and body["counts"]["alive"] == 1
    code, body = svc.dispatch("POST", "/api/clone.gc", {"dry_run": True})
    assert code == 200 and body["reclaimed"] == []
    # 幽灵心跳如实报错
    code, body = svc.dispatch("POST", "/api/clone.heartbeat", {"clone_id": "ghost"})
    assert code == 200 and "未登记" in body["error"]
    # 缺参 400
    code, body = svc.dispatch("POST", "/api/clone.register", {"clone_id": "x"})
    assert code == 400


def test_macro_rest_and_run_through_session(tmp_path):
    svc = _svc(tmp_path)
    code, _ = svc.dispatch("POST", "/api/session.create", {"session_id": "s1"})
    assert code == 200
    code, _ = svc.dispatch("POST", "/api/session.open_app",
                           {"session_id": "s1", "app_id": "desktop"})
    assert code == 200
    steps = [{"app_id": "desktop", "verb": "observe", "params": {}},
             {"app_id": "desktop", "verb": "windows", "params": {}}]
    code, body = svc.dispatch("POST", "/api/macro.save",
                              {"name": "看一眼", "steps": steps, "description": "感知一帧"})
    assert code == 200 and body["ok"] is True
    code, body = svc.dispatch("GET", "/api/macro.list", {})
    assert code == 200 and body["macros"][0]["name"] == "看一眼"
    # 重放：dry-run 底座下动词照样 ok（离线全链路）
    code, body = svc.dispatch("POST", "/api/macro.run",
                              {"name": "看一眼", "session_id": "s1"})
    assert code == 200 and body["ok"] is True and body["ran"] == 2
    code, body = svc.dispatch("POST", "/api/macro.delete", {"name": "看一眼"})
    assert code == 200 and body["deleted"] is True


def test_mcp_tools_cover_lifecycle_and_macros(tmp_path):
    svc = _svc(tmp_path)
    body, is_err = _call(svc, "clone_register", {"clone_id": "c1", "app_id": "notepad"})
    assert not is_err and body["state"] == "alive"
    body, is_err = _call(svc, "clone_health", {})
    assert not is_err and body["total"] == 1
    body, is_err = _call(svc, "clone_gc", {})
    assert not is_err and body["reclaimed"] == []
    body, is_err = _call(svc, "macro_save", {
        "name": "m", "steps": [{"app_id": "desktop", "verb": "observe"}]})
    assert not is_err and body["ok"] is True
    body, is_err = _call(svc, "macro_list", {})
    assert not is_err and body["macros"][0]["name"] == "m"


def test_tool_groups_cover_all_tools_and_lazy_list(tmp_path, monkeypatch):
    # 分组全覆盖：除两把钥匙外每个工具都归属唯一组
    grouped = [t for g in _TOOL_GROUPS.values() for t in g["tools"]]
    assert len(grouped) == len(set(grouped))
    assert set(grouped) == set(_TOOLS) - {"tool_groups", "expand_tools"}

    svc = _svc(tmp_path)
    body, is_err = _call(svc, "tool_groups", {})
    assert not is_err and {g["group"] for g in body["groups"]} == set(_TOOL_GROUPS)
    body, is_err = _call(svc, "expand_tools", {"group": "macro"})
    assert not is_err and {t["name"] for t in body["tools"]} == set(
        _TOOL_GROUPS["macro"]["tools"])
    body, is_err = _call(svc, "expand_tools", {"group": "nope"})
    assert is_err

    # 缺省全量呈现（兼容旧客户端）
    monkeypatch.delenv("DAO_MCP_LAZY", raising=False)
    r = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in r["result"]["tools"]}
    assert names == set(_TOOLS)
    # 懒加载呈现：只列核心组 + 两把钥匙；收敛只在呈现层，tools/call 全量可调
    monkeypatch.setenv("DAO_MCP_LAZY", "1")
    r = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    lazy_names = {t["name"] for t in r["result"]["tools"]}
    assert {"tool_groups", "expand_tools"} <= lazy_names
    assert "macro_run" not in lazy_names and "route" in lazy_names
    body, is_err = _call(svc, "macro_list", {})  # 未列出仍可调
    assert not is_err
