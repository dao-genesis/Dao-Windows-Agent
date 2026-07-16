"""第三方模型驱动 · 让任意 OpenAI 兼容 API 真实指挥调度整机原生工具层。

本源（无为而无不为）：Devin Cloud 之所以能调度自己的整机工具，靠的是「模型 ↔ 工具」
的 function-calling 闭环。本模块把 **同一套 dao-windows-agent 原生工具**（bridge/mcp.py
的 `_TOOLS`）暴露成 OpenAI function-calling 规格，交给第三方模型（DeepSeek / 小米 MiMo
等）自主规划、逐步调用，落到真实 BridgeService（或经 DAO_WIN_BRIDGE_URL 转发到远端桥）——
于是「用第三方 API 账号真实指挥模型调度这些工具」与 Devin Cloud 同构、可实战验证。

分层（各司其职，皆可离线单测）：
* `mcp_tools_openai()`     —— 把 MCP 工具清单转成 OpenAI `tools`（function）规格。
* `run_agent(...)`         —— 纯循环：喂模型 → 执行其 tool_calls（走真实工具）→ 回灌结果，
                             直至模型不再调用工具或触及步数上限。模型端抽象为 `ChatClient`，
                             故可用假客户端离线验证「工具确被真实调用且结果被回灌」。
* `OpenAICompatClient`     —— 纯标准库 urllib 的 OpenAI 兼容 HTTP 客户端（DeepSeek/MiMo 等）。
* `PROVIDERS` + `make_client_from_env()` —— 常见第三方厂商预设与从环境取密钥的便捷装配。

不引第三方依赖；密钥只经环境变量传入，绝不落盘。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from bridge.mcp import _call_tool, _tools_list


# ── 工具规格：MCP → OpenAI function ─────────────────────────────────────────────
def mcp_tools_openai() -> list[dict]:
    """把 bridge.mcp 的 MCP 工具清单转成 OpenAI `tools`（type=function）规格。

    与官方工具注册同构：name/description/parameters 逐字对应 MCP inputSchema，
    第三方模型据此即可 function-calling，无需任何额外适配。
    """
    out: list[dict] = []
    for t in _tools_list():
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
            },
        })
    return out


def execute_tool(name: str, arguments: dict | None) -> str:
    """执行一个原生工具并把结果序列化成给模型回灌的字符串（异常如实降级为 error 文本）。"""
    try:
        payload = _call_tool(name, arguments or {})
    except Exception as exc:  # 处理器异常绝不掀翻循环
        payload = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        return json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps({"result": str(payload)}, ensure_ascii=False)


# ── 模型端抽象 ──────────────────────────────────────────────────────────────────
class ChatClient(Protocol):
    """一次多轮补全：给定 messages 与 tools，返回一条 assistant 消息（可含 tool_calls）。"""

    def complete(self, messages: list[dict], tools: list[dict]) -> dict: ...


DEFAULT_SYSTEM = (
    "你是接入用户 Windows 电脑原生工具层(dao-windows-agent)的工程师。"
    "只能经工具操作整机与各软件：先 search_verbs/route 探明能力动词，勿臆测动词名；"
    "再 session_create 开隔离会话、session_open_app 打开软件、session_invoke 执行动词；"
    "任务完成后 session_destroy 释放会话。缺少必要信息(如文件路径)时如实说明，勿编造。"
)


@dataclass
class ToolCallRecord:
    step: int
    name: str
    arguments: dict
    result: str


@dataclass
class AgentRun:
    task: str
    steps: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    final_text: str = ""
    stopped_reason: str = ""  # "final" | "max_steps"
    messages: list[dict] = field(default_factory=list)

    def tool_names(self) -> list[str]:
        return [c.name for c in self.tool_calls]


def run_agent(
    task: str,
    client: ChatClient,
    *,
    system: str | None = None,
    max_steps: int = 12,
    tools: list[dict] | None = None,
    on_event: Callable[[str, dict], None] | None = None,
) -> AgentRun:
    """驱动第三方模型经原生工具层完成任务的闭环。

    每轮：把 messages+tools 交给模型 → 若返回 tool_calls 则逐个用真实工具执行并回灌 →
    直至模型不再调用工具（收敛出终答）或触及 max_steps。所有工具调用落真实 BridgeService。
    """
    tools = tools if tools is not None else mcp_tools_openai()
    messages: list[dict] = [
        {"role": "system", "content": system or DEFAULT_SYSTEM},
        {"role": "user", "content": task},
    ]
    run = AgentRun(task=task, messages=messages)

    def emit(kind: str, data: dict) -> None:
        if on_event:
            try:
                on_event(kind, data)
            except Exception:
                pass

    while run.steps < max_steps:
        run.steps += 1
        msg = client.complete(messages, tools)
        # 归一化：确保 assistant 消息带 role
        msg = dict(msg or {})
        msg.setdefault("role", "assistant")
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            run.final_text = msg.get("content") or ""
            run.stopped_reason = "final"
            emit("final", {"step": run.steps, "content": run.final_text})
            return run
        for c in calls:
            fn = (c.get("function") or {})
            name = fn.get("name", "")
            raw = fn.get("arguments")
            if isinstance(raw, dict):
                args = raw
            else:
                try:
                    args = json.loads(raw or "{}")
                except (TypeError, ValueError):
                    args = {}
            result = execute_tool(name, args)
            run.tool_calls.append(ToolCallRecord(run.steps, name, args, result))
            emit("tool", {"step": run.steps, "name": name, "arguments": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": c.get("id") or f"call_{len(run.tool_calls)}",
                "content": result,
            })
    run.stopped_reason = "max_steps"
    emit("max_steps", {"step": run.steps})
    return run


# ── OpenAI 兼容 HTTP 客户端（DeepSeek / 小米 MiMo / 任意兼容端点） ─────────────────
class OpenAICompatClient:
    """纯标准库的 OpenAI 兼容 chat/completions 客户端（function-calling）。"""

    def __init__(self, base_url: str, api_key: str, model: str, *,
                 timeout: float = 120.0, temperature: float = 0.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]


# 常见第三方厂商预设：base_url 与默认取密钥的环境变量名。
PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat",
                 "key_env": "DEEPSEEK_API_KEY"},
    # 实测 mimo-v2.5 基座不回 tool_calls（把工具调用写进 content），-pro 才有原生 function-calling
    "xiaomi-mimo": {"base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5-pro",
                    "key_env": "XIAOMI_MIMO_API_KEY"},
}


def make_client_from_env(provider: str, *, model: str | None = None,
                         api_key: str | None = None) -> OpenAICompatClient:
    """按厂商预设装配客户端；密钥优先用显式入参，否则取厂商约定环境变量或 DAO_MODEL_API_KEY。"""
    preset = PROVIDERS.get(provider)
    if preset is None:
        raise ValueError(f"未知厂商: {provider}（可选: {', '.join(PROVIDERS)}）")
    key = api_key or os.environ.get(preset["key_env"]) or os.environ.get("DAO_MODEL_API_KEY")
    if not key:
        raise RuntimeError(
            f"缺少密钥：设 {preset['key_env']} 或 DAO_MODEL_API_KEY，或显式传 api_key。")
    return OpenAICompatClient(preset["base_url"], key, model or preset["model"])


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # 非 UTF-8 码页 Windows 也能出中文
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="第三方模型驱动整机原生工具层（实战调度）")
    ap.add_argument("--task", required=True, help="自然语言任务")
    ap.add_argument("--provider", default="deepseek", choices=sorted(PROVIDERS))
    ap.add_argument("--model", default=None, help="覆盖厂商默认模型名")
    ap.add_argument("--max-steps", type=int, default=12)
    args = ap.parse_args(argv)

    client = make_client_from_env(args.provider, model=args.model)

    def on_event(kind: str, data: dict) -> None:
        if kind == "tool":
            print(f"[step {data['step']}] {data['name']}"
                  f"({json.dumps(data['arguments'], ensure_ascii=False)})")
            print(f"    -> {data['result'][:300]}")
        elif kind == "final":
            print(f"\n[FINAL @step {data['step']}]\n{data['content']}")

    run = run_agent(args.task, client, max_steps=args.max_steps, on_event=on_event)
    print(f"\n== 收敛: {run.stopped_reason} · 步数 {run.steps} · "
          f"工具调用 {len(run.tool_calls)} 次: {run.tool_names()} ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
