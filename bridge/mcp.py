"""MCP 外壳：JSON-RPC 2.0 over stdio，把 BridgeService 动作包成 MCP 工具。

    python3 -m bridge.mcp        # 经 stdin/stdout 讲 MCP，供 Devin/Claude/本插件即插即用

实现 initialize / tools/list / tools/call 三个核心方法（纯标准库）。工具集与
bridge/README.md 的暴露约定一一对应，命名沿用 ha-copilot 的 search/describe/run 三段式。
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable

from bridge.service import BridgeService

_SERVICE = BridgeService()

# 工具定义：name -> (说明, 入参 schema properties, 必填, handler)
_TOOLS: dict[str, dict] = {
    "list_apps": {
        "description": "列出所有已注册的软件画像 app_id（樸散則為器：新增软件=加一个 profile）。",
        "properties": {},
        "required": [],
        "handler": lambda a: _SERVICE.apps(),
    },
    "search_verbs": {
        "description": "跨所有软件语义检索能力动词（ha-copilot search_tools 配方）。先搜再调，勿臆测动词名。",
        "properties": {
            "query": {"type": "string", "description": "自然语言意图，如 '导出 gerber'"},
            "limit": {"type": "integer", "description": "返回条数，默认 10"},
        },
        "required": ["query"],
        "handler": lambda a: _SERVICE.search_verbs(a["query"], int(a.get("limit", 10))),
    },
    "describe_app": {
        "description": "查看某软件画像的动词表/参数/领域纪律（ha-copilot describe_tool 配方）。",
        "properties": {"app_id": {"type": "string"}},
        "required": ["app_id"],
        "handler": lambda a: _SERVICE.describe_app(a["app_id"]),
    },
    "session_create": {
        "description": "新建一个类虚拟机隔离会话（对应一个 IDE 窗口）。",
        "properties": {"session_id": {"type": "string", "description": "可选，缺省自动生成"}},
        "required": [],
        "handler": lambda a: _SERVICE.session_create(a.get("session_id")),
    },
    "session_list": {
        "description": "列出所有会话及各自已打开的软件。",
        "properties": {},
        "required": [],
        "handler": lambda a: _SERVICE.session_list(),
    },
    "session_open_app": {
        "description": "在指定会话内打开/附着一个软件实例（隔离并行、不上可见桌面）。",
        "properties": {"session_id": {"type": "string"}, "app_id": {"type": "string"}},
        "required": ["session_id", "app_id"],
        "handler": lambda a: _SERVICE.session_open_app(
            a["session_id"], a["app_id"],
            **{k: v for k, v in a.items() if k not in ("session_id", "app_id")},
        ),
    },
    "session_invoke": {
        "description": "在会话内对某软件执行一个高层动词（run）。params 为该动词的入参对象。",
        "properties": {
            "session_id": {"type": "string"},
            "app_id": {"type": "string"},
            "verb": {"type": "string"},
            "params": {"type": "object"},
        },
        "required": ["session_id", "app_id", "verb"],
        "handler": lambda a: _SERVICE.session_invoke(
            a["session_id"], a["app_id"], a["verb"], a.get("params")
        ),
    },
    "session_destroy": {
        "description": "销毁一个会话，释放其中所有软件实例。",
        "properties": {"session_id": {"type": "string"}},
        "required": ["session_id"],
        "handler": lambda a: _SERVICE.session_destroy(a["session_id"]),
    },
    "session_prompt": {
        "description": "获取该会话当前应注入 Agent 的帛书系统提示（含已开软件的领域纪律）。",
        "properties": {"session_id": {"type": "string"}},
        "required": ["session_id"],
        "handler": lambda a: _SERVICE.session_prompt(a["session_id"]),
    },
    "account_create": {
        "description": "创建/幂等更新一个 Windows 本地账号并加入 Remote Desktop Users（多账号类虚拟机·扩展本源）。"
                       "配合 RDPWrap 单机多会话，每账号一路独立桌面，与主账号并行互不干扰。",
        "properties": {
            "name": {"type": "string", "description": "账号名（字母数字与 . _ -，≤20）"},
            "password": {"type": "string", "description": "可选，缺省用实验默认口令"},
            "admin": {"type": "boolean", "description": "是否加入 Administrators，默认 false"},
        },
        "required": ["name"],
        "handler": lambda a: _SERVICE.account_create(a["name"], a.get("password"), bool(a.get("admin", False))),
    },
    "account_list": {
        "description": "列出账号（合并注册表 + quser 会话态）。password 永不外泄。",
        "properties": {},
        "required": [],
        "handler": lambda a: _SERVICE.account_list(),
    },
    "account_destroy": {
        "description": "注销账号所有会话并删除该本地账号（可选删 profile），从注册表摘除。",
        "properties": {
            "name": {"type": "string"},
            "delete_profile": {"type": "boolean", "description": "是否删除用户 profile 目录，默认 true"},
        },
        "required": ["name"],
        "handler": lambda a: _SERVICE.account_destroy(a["name"], bool(a.get("delete_profile", True))),
    },
    "account_sessions": {
        "description": "查看真机当前 RDP/控制台会话（quser 解析）。",
        "properties": {},
        "required": [],
        "handler": lambda a: _SERVICE.account_sessions(),
    },
}


def _tools_list() -> list[dict]:
    out = []
    for name, spec in _TOOLS.items():
        out.append({
            "name": name,
            "description": spec["description"],
            "inputSchema": {
                "type": "object",
                "properties": spec["properties"],
                "required": spec["required"],
            },
        })
    return out


def _call_tool(name: str, arguments: dict) -> dict:
    spec = _TOOLS.get(name)
    if spec is None:
        return {"error": f"未知工具: {name}"}
    for req in spec["required"]:
        if req not in arguments:
            return {"error": f"工具 {name} 缺少必填参数: {req}"}
    handler: Callable[[dict], Any] = spec["handler"]
    return handler(arguments)


def handle_request(req: dict) -> dict | None:
    """处理一条 JSON-RPC 请求；通知（无 id）返回 None。"""
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "dao-windows-agent-bridge", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {"tools": _tools_list()}
    elif method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        payload = _call_tool(name, arguments)
        result = {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": bool(isinstance(payload, dict) and payload.get("error")),
        }
    elif method in ("notifications/initialized", "initialized"):
        return None
    else:
        if req_id is None:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"未知方法: {method}"}}

    if req_id is None:
        return None
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
