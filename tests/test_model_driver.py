"""第三方模型驱动单测：用假 ChatClient 离线验证「模型 tool_calls 确被真实工具执行且结果回灌」，
以及工具规格转换、密钥装配、异常降级。纯逻辑，Linux/CI 即可跑。"""
from __future__ import annotations

import json

import pytest

from bridge import model_driver as md
from bridge.model_driver import (
    OpenAICompatClient,
    execute_tool,
    make_client_from_env,
    mcp_tools_openai,
    run_agent,
)


def test_mcp_tools_openai_shape():
    tools = mcp_tools_openai()
    names = {t["function"]["name"] for t in tools}
    # 与 MCP 原生工具面同构
    assert {"list_apps", "search_verbs", "session_create",
            "session_open_app", "session_invoke", "session_destroy"} <= names
    for t in tools:
        assert t["type"] == "function"
        fn = t["function"]
        assert isinstance(fn["description"], str) and fn["description"]
        assert fn["parameters"]["type"] == "object"


def test_execute_tool_runs_real_tool():
    out = json.loads(execute_tool("list_apps", {}))
    assert isinstance(out.get("apps"), list) and out["apps"]


def test_execute_tool_unknown_and_missing_param_are_honest():
    assert "未知工具" in json.loads(execute_tool("nope", {}))["error"]
    # search_verbs 缺必填 query → 如实报错，不抛异常掀翻循环
    assert "缺少必填参数" in json.loads(execute_tool("search_verbs", {}))["error"]


class ScriptedClient:
    """按脚本逐轮返回 assistant 消息；记录每轮收到的 messages 以便断言结果回灌。"""

    def __init__(self, script):
        self.script = list(script)
        self.seen_messages = []

    def complete(self, messages, tools):
        self.seen_messages.append([dict(m) for m in messages])
        return self.script.pop(0)


def _tool_call(cid, name, args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def test_run_agent_drives_real_tools_end_to_end():
    """模型脚本：search_verbs → session_create → open_app → destroy → 终答。
    断言真实工具被调用、结果被回灌进下一轮 messages。"""
    sid = "md-test-1"
    script = [
        {"role": "assistant", "content": None,
         "tool_calls": [_tool_call("c1", "search_verbs", {"query": "导出 gerber", "limit": 5})]},
        {"role": "assistant", "content": None,
         "tool_calls": [_tool_call("c2", "session_create", {"session_id": sid})]},
        {"role": "assistant", "content": None,
         "tool_calls": [_tool_call("c3", "session_open_app", {"session_id": sid, "app_id": "kicad"})]},
        {"role": "assistant", "content": None,
         "tool_calls": [_tool_call("c4", "session_destroy", {"session_id": sid})]},
        {"role": "assistant", "content": "已完成：探得动词、开合会话，KiCad 导出链路可用。"},
    ]
    client = ScriptedClient(script)
    run = run_agent("在 kicad 导出 gerber", client, max_steps=8)

    assert run.stopped_reason == "final"
    assert run.tool_names() == ["search_verbs", "session_create", "session_open_app", "session_destroy"]
    assert run.final_text.startswith("已完成")

    # search_verbs 真实命中 kicad export_gerbers
    first = json.loads(run.tool_calls[0].result)
    assert any(h.get("app_id") == "kicad" and "gerber" in h.get("verb", "")
               for h in first.get("hits", []))
    # open_app 真实成功
    assert json.loads(run.tool_calls[2].result)["ok"] is True
    # 结果确被回灌：最后一轮 messages 里含 role=tool 的工具结果
    last_seen = client.seen_messages[-1]
    tool_msgs = [m for m in last_seen if m.get("role") == "tool"]
    assert len(tool_msgs) == 4
    assert any(m["tool_call_id"] == "c1" for m in tool_msgs)


def test_run_agent_stops_on_max_steps():
    """模型永远只调用工具、不收敛 → 触及 max_steps 即停，如实标注。"""
    forever = [
        {"role": "assistant", "content": None,
         "tool_calls": [_tool_call(f"c{i}", "list_apps", {})]}
        for i in range(20)
    ]
    run = run_agent("循环", ScriptedClient(forever), max_steps=3)
    assert run.stopped_reason == "max_steps"
    assert run.steps == 3
    assert len(run.tool_calls) == 3


def test_run_agent_accepts_dict_arguments():
    """有些兼容端点把 arguments 直接给成 dict（非 JSON 字符串），也须正确执行。"""
    msg = {"role": "assistant", "content": None,
           "tool_calls": [{"id": "c1", "type": "function",
                           "function": {"name": "search_verbs",
                                        "arguments": {"query": "截屏", "limit": 2}}}]}
    run = run_agent("截屏", ScriptedClient([msg, {"role": "assistant", "content": "ok"}]))
    assert run.tool_names() == ["search_verbs"]
    assert "hits" in json.loads(run.tool_calls[0].result)


def test_make_client_from_env_presets(monkeypatch):
    monkeypatch.delenv("DAO_MODEL_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    c = make_client_from_env("deepseek")
    assert isinstance(c, OpenAICompatClient)
    assert c.base_url == "https://api.deepseek.com" and c.model == "deepseek-chat"
    assert c.api_key == "sk-x"

    monkeypatch.setenv("DAO_MODEL_API_KEY", "sk-generic")
    c2 = make_client_from_env("xiaomi-mimo", model="mimo-v2.5-pro")
    assert c2.base_url == "https://api.xiaomimimo.com/v1" and c2.model == "mimo-v2.5-pro"


def test_make_client_unknown_provider_and_missing_key(monkeypatch):
    with pytest.raises(ValueError):
        make_client_from_env("nope")
    monkeypatch.delenv("DAO_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        make_client_from_env("deepseek")


def test_providers_manifest():
    assert set(md.PROVIDERS) >= {"deepseek", "xiaomi-mimo"}
    for p in md.PROVIDERS.values():
        assert p["base_url"].startswith("https://")
        assert p["key_env"] and p["model"]
