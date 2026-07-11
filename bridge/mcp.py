"""MCP 外壳：JSON-RPC 2.0 over stdio，把 BridgeService 动作包成 MCP 工具。

    python3 -m bridge.mcp        # 经 stdin/stdout 讲 MCP，供 Devin/Claude/本插件即插即用

实现 initialize / tools/list / tools/call 三个核心方法（纯标准库）。工具集与
bridge/README.md 的暴露约定一一对应，命名沿用 ha-copilot 的 search/describe/run 三段式。

两种存在形态（与 ide/vscode/dao-mcp.js 注册的 env 约定对应）：
* 未设 `DAO_WIN_BRIDGE_URL` —— 在本进程内直接驱动 BridgeService（guest 内/单机）。
* 设了 `DAO_WIN_BRIDGE_URL`（可选 `DAO_WIN_TOKEN`） —— 作为纯代理，把同名动作
  转发到远端 bridge 的 /api/*（IDE 侧 MCP → Windows guest 的控制平面）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any, Callable

from bridge.service import BridgeService


class RemoteBridge:
    """把工具层动作转发到远端 bridge HTTP 接口（与 BridgeService 同名同义）。"""

    def __init__(self, base_url: str, token: str = "") -> None:
        self.base = base_url.rstrip("/")
        self.token = token

    def _req(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(payload or {}).encode() if method == "POST" else None
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())

    def apps(self):
        return self._req("GET", "/api/apps")

    def search_verbs(self, query: str, limit: int = 10):
        return self._req("POST", "/api/search_verbs", {"query": query, "limit": limit})

    def describe_app(self, app_id: str):
        return self._req("POST", "/api/describe_app", {"app_id": app_id})

    def session_create(self, session_id=None):
        return self._req("POST", "/api/session.create",
                         {"session_id": session_id} if session_id else {})

    def session_list(self):
        return self._req("GET", "/api/session.list")

    def session_open_app(self, session_id: str, app_id: str, **extra):
        return self._req("POST", "/api/session.open_app",
                         {"session_id": session_id, "app_id": app_id, **extra})

    def session_invoke(self, session_id: str, app_id: str, verb: str, params=None):
        return self._req("POST", "/api/session.invoke",
                         {"session_id": session_id, "app_id": app_id,
                          "verb": verb, "params": params or {}})

    def session_destroy(self, session_id: str):
        return self._req("POST", "/api/session.destroy", {"session_id": session_id})

    def session_prompt(self, session_id: str):
        return self._req("POST", "/api/session.prompt", {"session_id": session_id})

    def route(self, text: str, verb_limit: int = 5):
        return self._req("POST", "/api/route", {"text": text, "verb_limit": verb_limit})

    def capabilities(self):
        return self._req("GET", "/api/capabilities")

    def account_create(self, name: str, password=None, admin: bool = False):
        return self._req("POST", "/api/account.create",
                         {"name": name, "password": password, "admin": admin})

    def account_list(self):
        return self._req("GET", "/api/account.list")

    def account_destroy(self, name: str, delete_profile: bool = True):
        return self._req("POST", "/api/account.destroy",
                         {"name": name, "delete_profile": delete_profile})

    def account_sessions(self):
        return self._req("GET", "/api/account.sessions")


def _make_service():
    url = os.environ.get("DAO_WIN_BRIDGE_URL", "").strip()
    if url:
        return RemoteBridge(url, os.environ.get("DAO_WIN_TOKEN", "").strip())
    return BridgeService()


_SERVICE = _make_service()

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
    "route": {
        "description": "通用适配层 @ 调度：把一句自然语言目标裁定到整机通用层或被 @句柄 唤起的领域工作层，"
                       "并给出跨层动词候选。无 @ → 整机通用层(system)；@kicad/@freecad… → 对应专用工作层。"
                       "先 route 定层与候选动词，再 session_invoke 执行。",
        "properties": {
            "text": {"type": "string", "description": "自然语言目标，可含 @句柄，如 '@kicad 导出 gerber'"},
            "verb_limit": {"type": "integer", "description": "动词候选条数，默认 5"},
        },
        "required": ["text"],
        "handler": lambda a: _SERVICE.route(a["text"], int(a.get("verb_limit", 5))),
    },
    "capabilities": {
        "description": "统一能力清单：整机通用层 + 各 @句柄领域工作层（builtin/external 一视同仁）。"
                       "Agent 一览而择路——无 @ 操作整机，需专门领域能力时 @对应句柄 唤起工作层。",
        "properties": {},
        "required": [],
        "handler": lambda a: _SERVICE.capabilities(),
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
