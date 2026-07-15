"""MCP 外壳单测：服务形态选择(共享会话态归一) + JSON-RPC 处理，纯逻辑离线跑。"""
from __future__ import annotations

import json

from bridge import mcp as mcp_mod
from bridge.mcp import RemoteBridge, _make_service, handle_request
from bridge.service import BridgeService


def test_explicit_remote_url_wins(monkeypatch):
    monkeypatch.setenv("DAO_WIN_BRIDGE_URL", "http://10.0.0.9:9930")
    monkeypatch.setenv("DAO_WIN_TOKEN", "t0")
    svc = _make_service()
    assert isinstance(svc, RemoteBridge)
    assert svc.base == "http://10.0.0.9:9930" and svc.token == "t0"


def test_attaches_to_live_local_bridge(monkeypatch):
    monkeypatch.delenv("DAO_WIN_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DAO_WIN_LOCAL_BRIDGE", raising=False)
    monkeypatch.setenv("DAO_WIN_TOKEN", "t1")
    monkeypatch.setattr(mcp_mod, "_probe_local_bridge", lambda base, token="": True)
    svc = _make_service()
    assert isinstance(svc, RemoteBridge)
    assert svc.base == mcp_mod._LOCAL_PROBE_URLS[0] and svc.token == "t1"


def test_probes_fall_through_candidates(monkeypatch):
    monkeypatch.delenv("DAO_WIN_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DAO_WIN_LOCAL_BRIDGE", raising=False)
    alive = mcp_mod._LOCAL_PROBE_URLS[1]
    monkeypatch.setattr(mcp_mod, "_probe_local_bridge", lambda base, token="": base == alive)
    svc = _make_service()
    assert isinstance(svc, RemoteBridge) and svc.base == alive


def test_falls_back_to_inprocess_when_no_bridge(monkeypatch):
    monkeypatch.delenv("DAO_WIN_BRIDGE_URL", raising=False)
    monkeypatch.setattr(mcp_mod, "_probe_local_bridge", lambda base, token="": False)
    assert isinstance(_make_service(), BridgeService)


def test_local_probe_url_env_override(monkeypatch):
    monkeypatch.delenv("DAO_WIN_BRIDGE_URL", raising=False)
    monkeypatch.setenv("DAO_WIN_LOCAL_BRIDGE", "http://127.0.0.1:12345")
    seen = {}

    def probe(base, token=""):
        seen["base"] = base
        return True
    monkeypatch.setattr(mcp_mod, "_probe_local_bridge", probe)
    svc = _make_service()
    assert isinstance(svc, RemoteBridge) and svc.base == "http://127.0.0.1:12345"
    assert seen["base"] == "http://127.0.0.1:12345"


def test_probe_failure_is_honest_false():
    assert mcp_mod._probe_local_bridge("http://127.0.0.1:1") is False


def test_handle_request_initialize_and_bad_tool():
    r = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r["result"]["serverInfo"]["name"] == "dao-windows-agent-bridge"
    r2 = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": "nope", "arguments": {}}})
    assert r2["result"]["isError"] is True
    payload = json.loads(r2["result"]["content"][0]["text"])
    assert "未知工具" in payload["error"]
