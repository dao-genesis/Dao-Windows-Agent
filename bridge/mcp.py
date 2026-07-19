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
import urllib.error
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

    def mode_list(self):
        return self._req("GET", "/api/mode.list")

    def mode_get(self):
        return self._req("GET", "/api/mode.get")

    def mode_set(self, mode_id: str):
        return self._req("POST", "/api/mode.set", {"mode": mode_id})

    def project_create(self, project_id: str, goal: str = "", stages=None):
        return self._req("POST", "/api/project.create",
                         {"project_id": project_id, "goal": goal, "stages": stages or []})

    def project_advance(self, project_id: str, artifacts=None, note: str = ""):
        return self._req("POST", "/api/project.advance",
                         {"project_id": project_id, "artifacts": artifacts, "note": note})

    def project_status(self, project_id: str):
        return self._req("POST", "/api/project.status", {"project_id": project_id})

    def project_list(self):
        return self._req("GET", "/api/project.list")

    def env_report(self):
        return self._req("GET", "/api/env.report")

    def env_probe(self):
        return self._req("GET", "/api/env.probe")

    def env_provision(self, apply: bool = False):
        return self._req("POST", "/api/env.provision", {"apply": apply})

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

    def desktop_plan(self, session_id: str, want: str = "desktop"):
        return self._req("POST", "/api/desktop.plan",
                         {"session_id": session_id, "want": want})

    def desktop_ensure(self, session_id: str, approve_provision: bool = False,
                       approve_account: bool = False,
                       approve_activate: bool = False, password=None):
        return self._req("POST", "/api/desktop.ensure",
                         {"session_id": session_id,
                          "approve_provision": approve_provision,
                          "approve_account": approve_account,
                          "approve_activate": approve_activate, "password": password})

    def desktop_status(self, session_id: str):
        return self._req("POST", "/api/desktop.status", {"session_id": session_id})

    def desktop_discover(self):
        return self._req("GET", "/api/desktop.discover")

    def desktop_release(self, session_id: str, approve: bool = False,
                        delete_profile: bool = True):
        return self._req("POST", "/api/desktop.release",
                         {"session_id": session_id, "approve": approve,
                          "delete_profile": delete_profile})

    def rdp_session_list(self):
        return self._req("GET", "/api/rdp.list")

    def rdp_session_activate(self, username: str, password: str, index: int = 0,
                             approve: bool = False):
        return self._req("POST", "/api/rdp.activate",
                         {"username": username, "password": password,
                          "index": index, "approve": approve})

    def rdp_session_logoff(self, username: str = "", session_id: str = "",
                           approve: bool = False):
        return self._req("POST", "/api/rdp.logoff",
                         {"username": username, "session_id": session_id,
                          "approve": approve})

    def clone_plan(self, app_id: str, clone_id: str, tiers=None,
                   prefer_strongest: bool = False, auto_detect: bool = False):
        return self._req("POST", "/api/clone.plan",
                         {"app_id": app_id, "clone_id": clone_id,
                          "tiers": tiers, "prefer_strongest": prefer_strongest,
                          "auto_detect": auto_detect})

    def clone_matrix(self, app_ids, tiers=None, prefer_strongest: bool = False,
                     auto_detect: bool = False):
        return self._req("POST", "/api/clone.matrix",
                         {"app_ids": app_ids, "tiers": tiers,
                          "prefer_strongest": prefer_strongest,
                          "auto_detect": auto_detect})

    def clone_register(self, clone_id: str, app_id: str, tier: str = "", ttl=None):
        return self._req("POST", "/api/clone.register",
                         {"clone_id": clone_id, "app_id": app_id,
                          "tier": tier, "ttl": ttl})

    def clone_heartbeat(self, clone_id: str):
        return self._req("POST", "/api/clone.heartbeat", {"clone_id": clone_id})

    def clone_health(self):
        return self._req("GET", "/api/clone.health")

    def clone_gc(self, dry_run: bool = False):
        return self._req("POST", "/api/clone.gc", {"dry_run": dry_run})

    def macro_list(self):
        return self._req("GET", "/api/macro.list")

    def macro_get(self, name: str):
        return self._req("POST", "/api/macro.get", {"name": name})

    def macro_save(self, name: str, steps, description: str = ""):
        return self._req("POST", "/api/macro.save",
                         {"name": name, "steps": steps, "description": description})

    def macro_delete(self, name: str):
        return self._req("POST", "/api/macro.delete", {"name": name})

    def macro_run(self, name: str, session_id: str, overrides=None):
        return self._req("POST", "/api/macro.run",
                         {"name": name, "session_id": session_id,
                          "overrides": overrides})


# 本机桥候选：bridge.server 默认 9930；guest 置备(start-bridge.ps1)常用 9920
_LOCAL_PROBE_URLS = ("http://127.0.0.1:9930", "http://127.0.0.1:9920")


def _probe_local_bridge(base: str, token: str = "") -> bool:
    """本机桥探活 + 验明正身 + 鉴权自证：三关全过才视为可附着。

    真机（VPS）实证暴露的两类盲附事故：
    1. 同端口有一路 **他人的 token 保护桥**——/api/health 照样 2xx，盲附后每次
       真实工具调用都拿 401（不透明失败，且污染测试）。
    2. 同端口有一路 **任意路径都回 200 的冒名服务**（如模拟器/echo 服务）——探活
       与鉴权全过，但响应结构完全不对，下游取键即 KeyError。
    故探针要求：/api/health 回 `{"ok": true}`（本桥指纹），且带 token 的 /api/apps
    回含 `apps` 键的 2xx。任一不满足即判不可用，回退进程内直驱或下一候选。
    """
    base = base.rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=2) as resp:
            if not (200 <= resp.status < 300):
                return False
            health = json.loads(resp.read())
        if not (isinstance(health, dict) and health.get("ok") is True):
            return False
    except (urllib.error.URLError, OSError, ValueError):
        return False
    # 鉴权自证：/api/apps 在设了 token 的桥上需 Bearer；无 token 桥则任何请求皆 2xx。
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(base + "/api/apps", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            if not (200 <= resp.status < 300):
                return False
            apps = json.loads(resp.read())
        return isinstance(apps, dict) and "apps" in apps
    except urllib.error.HTTPError:
        # 401/403（token 不匹配/缺失）或其它 HTTP 错误：此桥不可用，勿附着。
        return False
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _make_service():
    url = os.environ.get("DAO_WIN_BRIDGE_URL", "").strip()
    token = os.environ.get("DAO_WIN_TOKEN", "").strip()
    if url:
        return RemoteBridge(url, token)
    # 会话态归一：本机若已有活桥，stdio MCP 附着其上（HTTP 与 MCP 共享同一套
    # 会话/模式/工程流水），而非各起一份割裂的内存态。探活/鉴权失败才退回进程内直驱。
    env_probe = os.environ.get("DAO_WIN_LOCAL_BRIDGE", "").strip()
    candidates = (env_probe,) if env_probe else _LOCAL_PROBE_URLS
    for probe in candidates:
        if _probe_local_bridge(probe, token):
            return RemoteBridge(probe, token)
    return BridgeService()


# 惰性裁定：首次工具调用才选形态。HTTP 桥(bridge.server) import 本模块只为复用
# handle_request，若 import 即探活会误附着到旧桥/自身端口，故延至真用时。
_SERVICE = None


def _default_service():
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = _make_service()
    return _SERVICE

# 工具定义：name -> (说明, 入参 schema properties, 必填, handler)
_TOOLS: dict[str, dict] = {
    "list_apps": {
        "description": "列出所有已注册的软件画像 app_id（樸散則為器：新增软件=加一个 profile）。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.apps(),
    },
    "search_verbs": {
        "description": "跨所有软件语义检索能力动词（ha-copilot search_tools 配方）。先搜再调，勿臆测动词名。",
        "properties": {
            "query": {"type": "string", "description": "自然语言意图，如 '导出 gerber'"},
            "limit": {"type": "integer", "description": "返回条数，默认 10"},
        },
        "required": ["query"],
        "handler": lambda s, a: s.search_verbs(a["query"], int(a.get("limit", 10))),
    },
    "describe_app": {
        "description": "查看某软件画像的动词表/参数/领域纪律（ha-copilot describe_tool 配方）。",
        "properties": {"app_id": {"type": "string"}},
        "required": ["app_id"],
        "handler": lambda s, a: s.describe_app(a["app_id"]),
    },
    "session_create": {
        "description": "新建一个类虚拟机隔离会话（对应一个 IDE 窗口）。",
        "properties": {"session_id": {"type": "string", "description": "可选，缺省自动生成"}},
        "required": [],
        "handler": lambda s, a: s.session_create(a.get("session_id")),
    },
    "session_list": {
        "description": "列出所有会话及各自已打开的软件。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.session_list(),
    },
    "session_open_app": {
        "description": "在指定会话内打开/附着一个软件实例（隔离并行、不上可见桌面）。",
        "properties": {"session_id": {"type": "string"}, "app_id": {"type": "string"}},
        "required": ["session_id", "app_id"],
        "handler": lambda s, a: s.session_open_app(
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
        "handler": lambda s, a: s.session_invoke(
            a["session_id"], a["app_id"], a["verb"], a.get("params")
        ),
    },
    "session_destroy": {
        "description": "销毁一个会话，释放其中所有软件实例。",
        "properties": {"session_id": {"type": "string"}},
        "required": ["session_id"],
        "handler": lambda s, a: s.session_destroy(a["session_id"]),
    },
    "session_prompt": {
        "description": "获取该会话当前应注入 Agent 的帛书系统提示（含已开软件的领域纪律）。",
        "properties": {"session_id": {"type": "string"}},
        "required": ["session_id"],
        "handler": lambda s, a: s.session_prompt(a["session_id"]),
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
        "handler": lambda s, a: s.route(a["text"], int(a.get("verb_limit", 5))),
    },
    "capabilities": {
        "description": "统一能力清单：整机通用层 + 各 @句柄领域工作层（builtin/external 一视同仁）。"
                       "Agent 一览而择路——无 @ 操作整机，需专门领域能力时 @对应句柄 唤起工作层。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.capabilities(),
    },
    "mode_list": {
        "description": "列出全部可切换模式（primary/coding/windows/native/domain:<app_id>…）及当前模式。"
                       "模式 = 提示词覆盖 + 工具面裁剪（Proxy Pro 联动的三插件融合枢纽）。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.mode_list(),
    },
    "mode_get": {
        "description": "查看当前模式与该模式下开放的 app 工具面（allowed_apps）。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.mode_get(),
    },
    "mode_set": {
        "description": "切换模式（态持久化到 ~/.dao/mode.json，Proxy Pro/dao-desktop 同装联动）。"
                       "route/invoke 提示被模式挡住时，先切到对应模式再执行。",
        "properties": {"mode": {"type": "string", "description": "模式 id，如 windows / coding / domain:kicad"}},
        "required": ["mode"],
        "handler": lambda s, a: s.mode_set(a["mode"]),
    },
    "project_create": {
        "description": "创建一条跨领域工程交接流水（螺旋递进：各领域工作层完成后交接下一环节）。",
        "properties": {
            "project_id": {"type": "string"},
            "goal": {"type": "string", "description": "工程总目标"},
            "stages": {"type": "array", "description": "阶段清单，每项 {app_id, goal}"},
        },
        "required": ["project_id"],
        "handler": lambda s, a: s.project_create(a["project_id"], a.get("goal", ""), a.get("stages")),
    },
    "project_advance": {
        "description": "完成当前阶段并交接下一环节（可附产物路径与备注）。",
        "properties": {
            "project_id": {"type": "string"},
            "artifacts": {"type": "array", "description": "本阶段产物（文件路径等）"},
            "note": {"type": "string"},
        },
        "required": ["project_id"],
        "handler": lambda s, a: s.project_advance(a["project_id"], a.get("artifacts"), a.get("note", "")),
    },
    "project_status": {
        "description": "查看某工程流水的阶段进度与交接提示。",
        "properties": {"project_id": {"type": "string"}},
        "required": ["project_id"],
        "handler": lambda s, a: s.project_status(a["project_id"]),
    },
    "project_list": {
        "description": "列出全部工程交接流水。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.project_list(),
    },
    "env_report": {
        "description": "任意环境适配全景：探测本机 Windows 版本家族/内部版本/管理员态/RDP/多会话/RDPWrap，"
                       "裁定当前可用与可配备的隔离档位，推荐桌面路由主线（A 多会话/B 虚拟显示器/C 无头/Z 冷启动），"
                       "并出幂等配备计划。任意设备任意状态都给一条落地路径。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.env_report(),
    },
    "env_probe": {
        "description": "只做能力探测：返回本机 Windows 版本家族/内部版本/管理员/域/RDP 开关/单会话限制/RDPWrap 等原始快照。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.env_probe(),
    },
    "env_provision": {
        "description": "把多会话隔离抬升到可用：apply=false（缺省）只出幂等·可逆的配备计划（开 RDP/放开单会话/装 RDPWrap），"
                       "apply=true 才逐步执行并如实回报；无管理员/版本不支持时如实降级，绝不假装成功。",
        "properties": {
            "apply": {"type": "boolean", "description": "true 才真正执行配备步骤，缺省 false 只出计划"},
        },
        "required": [],
        "handler": lambda s, a: s.env_provision(bool(a.get("apply", False))),
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
        "handler": lambda s, a: s.account_create(a["name"], a.get("password"), bool(a.get("admin", False))),
    },
    "account_list": {
        "description": "列出账号（合并注册表 + quser 会话态）。password 永不外泄。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.account_list(),
    },
    "account_destroy": {
        "description": "注销账号所有会话并删除该本地账号（可选删 profile），从注册表摘除。",
        "properties": {
            "name": {"type": "string"},
            "delete_profile": {"type": "boolean", "description": "是否删除用户 profile 目录，默认 true"},
        },
        "required": ["name"],
        "handler": lambda s, a: s.account_destroy(a["name"], bool(a.get("delete_profile", True))),
    },
    "account_sessions": {
        "description": "查看真机当前 RDP/控制台会话（quser 解析）。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.account_sessions(),
    },
    "desktop_plan": {
        "description": "桌面级会话经纪（一窗一路）：为一个 IDE 窗口 session_id 出「探测→选路→配备计划→待授权项」落地计划（dry-run，不改真机）。"
                       "多会话路线（A）时绑定专属账号并列出需用户同意的写操作（开 RDP/建号）。",
        "properties": {
            "session_id": {"type": "string", "description": "IDE 窗口句柄（一窗一路）"},
            "want": {"type": "string", "description": "期望能力，缺省 desktop"},
        },
        "required": ["session_id"],
        "handler": lambda s, a: s.desktop_plan(a["session_id"], str(a.get("want") or "desktop")),
    },
    "desktop_ensure": {
        "description": "桌面级会话经纪：把一窗一路推进到「就绪」(含可选激活)。每步受知情同意门禁："
                       "approve_provision→开RDP/放开单会话/装RDPWrap；approve_account→建专属账号(分配回环IP)；"
                       "approve_activate→凭据入库+mstsc回环拉起使会话Active。"
                       "未授权即诚实返回blocked+pending，绝不擅自改机器；就绪后返回不含密码的guacd渲染描述符。",
        "properties": {
            "session_id": {"type": "string"},
            "approve_provision": {"type": "boolean", "description": "同意对本机执行 RDP/多会话配备（可回滚）"},
            "approve_account": {"type": "boolean", "description": "同意创建本窗口专属本地账号+分配回环地址（可 release 回滚）"},
            "approve_activate": {"type": "boolean", "description": "同意凭据入库+mstsc 回环拉起使会话 Active（可 logoff 回收）"},
            "password": {"type": "string", "description": "可选，缺省用默认口令（仅存本机凭据管理器）"},
        },
        "required": ["session_id"],
        "handler": lambda s, a: s.desktop_ensure(
            a["session_id"], bool(a.get("approve_provision", False)),
            bool(a.get("approve_account", False)),
            bool(a.get("approve_activate", False)), a.get("password")),
    },
    "desktop_discover": {
        "description": "只读发现真机已有的 account→loopback 映射（.rdp 文件+Credential Manager），含已用/下一可用回环地址。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.desktop_discover(),
    },
    "desktop_status": {
        "description": "桌面级会话经纪：查一窗一路当前状态（是否已绑定账号/会话态/不含密码的渲染描述符）。",
        "properties": {"session_id": {"type": "string"}},
        "required": ["session_id"],
        "handler": lambda s, a: s.desktop_status(a["session_id"]),
    },
    "desktop_release": {
        "description": "桌面级会话经纪：释放一窗一路——注销会话 + 删「本层派生」账号（受 approve 门禁·可逆）。",
        "properties": {
            "session_id": {"type": "string"},
            "approve": {"type": "boolean", "description": "同意删除本窗口专属账号及 profile"},
            "delete_profile": {"type": "boolean", "description": "是否删 profile 目录，默认 true"},
        },
        "required": ["session_id"],
        "handler": lambda s, a: s.desktop_release(
            a["session_id"], bool(a.get("approve", False)),
            bool(a.get("delete_profile", True))),
    },
    "rdp_session_list": {
        "description": "会话激活层：列真机当前所有 Windows 会话（qwinsta：sessionname/username/id/state/active）。只读。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.rdp_session_list(),
    },
    "rdp_session_activate": {
        "description": "会话激活层：把一路账号点亮成一路 Active 桌面——凭据入库(cmdkey)+回环拉起(mstsc 127.0.0.N)。"
                       "写操作受 approve 门禁；未授权即诚实返回 blocked。主控制台与既有会话不受影响，可 rdp_session_logoff 回收。",
        "properties": {
            "username": {"type": "string", "description": "目标本地账号名"},
            "password": {"type": "string", "description": "该账号口令（仅入本机凭据管理器，不外泄）"},
            "index": {"type": "integer", "description": "一路序号(0起) → 专属回环 127.0.0.(2+index)"},
            "approve": {"type": "boolean", "description": "同意写入凭据并拉起 RDP 会话"},
        },
        "required": ["username", "password"],
        "handler": lambda s, a: s.rdp_session_activate(
            a["username"], a["password"], int(a.get("index", 0)),
            bool(a.get("approve", False))),
    },
    "rdp_session_logoff": {
        "description": "会话激活层：注销 Windows 会话（按账号名或会话ID·可逆清理·受 approve 门禁）。",
        "properties": {
            "username": {"type": "string", "description": "按账号名注销（二选一）"},
            "session_id": {"type": "string", "description": "按会话ID注销（二选一）"},
            "approve": {"type": "boolean", "description": "同意注销"},
        },
        "required": [],
        "handler": lambda s, a: s.rdp_session_logoff(
            str(a.get("username") or ""), str(a.get("session_id") or ""),
            bool(a.get("approve", False))),
    },
    "clone_plan": {
        "description": "通用隔离层：为“分身 clone_id 隔离运行 app_id”选出隔离档位"
                       "（account/session/desktop/appdata）并如实报告能否真隔离。",
        "properties": {
            "app_id": {"type": "string", "description": "软件键（如 vscode/devin-desktop/wechat）"},
            "clone_id": {"type": "string", "description": "分身号（如 session-2）"},
            "tiers": {"type": "array", "items": {"type": "string"},
                      "description": "环境可用档位；缺省零配置三档 none/appdata/desktop"},
            "prefer_strongest": {"type": "boolean", "description": "真时选最强档而非最省档"},
            "auto_detect": {"type": "boolean",
                            "description": "真且未显式给 tiers 时，用本机 env 探测出的当前可用档位自动适配"},
        },
        "required": ["app_id", "clone_id"],
        "handler": lambda s, a: s.clone_plan(
            a["app_id"], a["clone_id"], a.get("tiers"),
            bool(a.get("prefer_strongest", False)), bool(a.get("auto_detect", False))),
    },
    "clone_matrix": {
        "description": "通用隔离层：一次算出多软件在当前可用档位下的隔离方案矩阵。",
        "properties": {
            "app_ids": {"type": "array", "items": {"type": "string"}},
            "tiers": {"type": "array", "items": {"type": "string"}},
            "prefer_strongest": {"type": "boolean"},
            "auto_detect": {"type": "boolean",
                            "description": "真且未显式给 tiers 时，用本机 env 探测出的当前可用档位自动适配"},
        },
        "required": ["app_ids"],
        "handler": lambda s, a: s.clone_matrix(
            a["app_ids"], a.get("tiers"), bool(a.get("prefer_strongest", False)),
            bool(a.get("auto_detect", False))),
    },
    "clone_register": {
        "description": "分身治理：登记一个已启动的分身并记首次心跳（建了就有人管·对称租约 TTL）。",
        "properties": {
            "clone_id": {"type": "string", "description": "分身号"},
            "app_id": {"type": "string", "description": "软件键"},
            "tier": {"type": "string", "description": "隔离档位(clone_plan 裁决结果·可选)"},
            "ttl": {"type": "number", "description": "心跳 TTL 秒，默认 90"},
        },
        "required": ["clone_id", "app_id"],
        "handler": lambda s, a: s.clone_register(
            a["clone_id"], a["app_id"], a.get("tier", ""), a.get("ttl")),
    },
    "clone_heartbeat": {
        "description": "分身治理：为已登记分身续一次心跳（久无心跳 → stale → expired → gc 回收）。",
        "properties": {"clone_id": {"type": "string"}},
        "required": ["clone_id"],
        "handler": lambda s, a: s.clone_heartbeat(a["clone_id"]),
    },
    "clone_health": {
        "description": "分身治理：全体分身存活快照（alive/stale/expired 三态裁决 + 汇总计数）。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.clone_health(),
    },
    "clone_gc": {
        "description": "分身治理：回收已 expired 的分身（dry_run=true 只预演不摘除）。",
        "properties": {"dry_run": {"type": "boolean", "description": "真=只报告将回收谁"}},
        "required": [],
        "handler": lambda s, a: s.clone_gc(bool(a.get("dry_run", False))),
    },
    "macro_list": {
        "description": "宏沉淀层：列出已固化的复合动词（成功动词序列的经验沉淀）。",
        "properties": {},
        "required": [],
        "handler": lambda s, a: s.macro_list(),
    },
    "macro_get": {
        "description": "宏沉淀层：查看某宏的完整步骤（app_id/verb/params 序列）。",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "handler": lambda s, a: s.macro_get(a["name"]),
    },
    "macro_save": {
        "description": "宏沉淀层：把一段已被证明成功的动词序列固化成宏（下次一句话整段重放）。"
                       "steps 每项 {app_id, verb, params}。",
        "properties": {
            "name": {"type": "string"},
            "steps": {"type": "array", "description": "步骤序列，每项 {app_id, verb, params}"},
            "description": {"type": "string"},
        },
        "required": ["name", "steps"],
        "handler": lambda s, a: s.macro_save(a["name"], a["steps"], a.get("description", "")),
    },
    "macro_delete": {
        "description": "宏沉淀层：删除一个已固化的宏。",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "handler": lambda s, a: s.macro_delete(a["name"]),
    },
    "macro_run": {
        "description": "宏沉淀层：在指定会话内整段重放一个宏（任一步失败即如实停下）。"
                       "overrides 可按步序号覆盖参数，如 {\"0\": {\"path\": \"...\"}}。",
        "properties": {
            "name": {"type": "string"},
            "session_id": {"type": "string"},
            "overrides": {"type": "object", "description": "{步序号: 参数覆盖}"},
        },
        "required": ["name", "session_id"],
        "handler": lambda s, a: s.macro_run(a["name"], a["session_id"], a.get("overrides")),
    },
}


# —— R11 工具目录分组/懒加载（对齐 Devin find_command/新工具面收敛思想）——
# 组划分只作用于 tools/list 的呈现；tools/call 永远可调全量工具（能力不因呈现收敛而丢失）。
_TOOL_GROUPS: dict[str, dict] = {
    "discover": {
        "description": "发现与调度：先搜再调（route/search_verbs/describe_app/capabilities）。",
        "tools": ("list_apps", "search_verbs", "describe_app", "route", "capabilities"),
    },
    "session": {
        "description": "会话生命周期与动词执行（一 IDE 窗口一会话）。",
        "tools": ("session_create", "session_list", "session_open_app",
                  "session_invoke", "session_destroy", "session_prompt"),
    },
    "mode": {
        "description": "模式（提示词覆盖 + 工具面裁剪）。",
        "tools": ("mode_list", "mode_get", "mode_set"),
    },
    "project": {
        "description": "跨领域工程交接流水。",
        "tools": ("project_create", "project_advance", "project_status", "project_list"),
    },
    "env": {
        "description": "任意环境适配（能力探测 + 档位裁定 + 桌面路由选路 + 幂等配备）。",
        "tools": ("env_report", "env_probe", "env_provision"),
    },
    "account": {
        "description": "多账号类虚拟机（Windows 本地账号 + RDP 会话）。",
        "tools": ("account_create", "account_list", "account_destroy", "account_sessions"),
    },
    "desktop": {
        "description": "桌面级会话经纪（一窗一路：探测→选路→知情同意后配备+建号→guacd 渲染描述符·可回滚）+ 会话激活（点亮/枚举/回收真机 Windows 会话）。",
        "tools": ("desktop_plan", "desktop_ensure", "desktop_discover",
                  "desktop_status", "desktop_release",
                  "rdp_session_list", "rdp_session_activate", "rdp_session_logoff"),
    },
    "clone": {
        "description": "分身隔离与生命周期治理（隔离裁决 + 心跳 + 超时回收）。",
        "tools": ("clone_plan", "clone_matrix", "clone_register",
                  "clone_heartbeat", "clone_health", "clone_gc"),
    },
    "macro": {
        "description": "宏沉淀层：成功动词序列固化为复合动词。",
        "tools": ("macro_list", "macro_get", "macro_save", "macro_delete", "macro_run"),
    },
}

# 懒加载时默认呈现的核心组（发现 + 会话即可起步；其余组经 expand_tools 按需展开）。
_CORE_GROUPS = ("discover", "session")


def _spec_entry(name: str, spec: dict) -> dict:
    return {
        "name": name,
        "description": spec["description"],
        "inputSchema": {
            "type": "object",
            "properties": spec["properties"],
            "required": spec["required"],
        },
    }


def _expand_tools(group: str) -> dict:
    g = _TOOL_GROUPS.get(group)
    if g is None:
        return {"error": f"未知工具组: {group}（可用: {sorted(_TOOL_GROUPS)}）"}
    return {"group": group, "description": g["description"],
            "tools": [_spec_entry(n, _TOOLS[n]) for n in g["tools"]]}


_TOOLS["tool_groups"] = {
    "description": "工具目录鸟瞰：列出全部工具组（组名/说明/各组工具名）。"
                    "懒加载形态下先看组、再 expand_tools 展开所需组——不必吞下全量目录。",
    "properties": {},
    "required": [],
    "handler": lambda s, a: {"groups": [
        {"group": k, "description": v["description"], "tools": list(v["tools"])}
        for k, v in _TOOL_GROUPS.items()]},
}
_TOOLS["expand_tools"] = {
    "description": "按组展开工具定义（入参 schema 全量）。展开的工具本就可直接 tools/call。",
    "properties": {"group": {"type": "string", "description": "组名，见 tool_groups"}},
    "required": ["group"],
    "handler": lambda s, a: _expand_tools(a["group"]),
}


def _lazy_enabled() -> bool:
    return os.environ.get("DAO_MCP_LAZY", "").strip().lower() in ("1", "true", "yes", "on")


def _tools_list() -> list[dict]:
    """tools/list 呈现。缺省全量（兼容既有客户端）；置 DAO_MCP_LAZY=1 则懒加载：
    只列核心组（discover/session）+ tool_groups/expand_tools 两把钥匙，其余组按需展开。
    收敛只在呈现层——tools/call 永远可调全量工具。"""
    if _lazy_enabled():
        names: list[str] = []
        for g in _CORE_GROUPS:
            names.extend(_TOOL_GROUPS[g]["tools"])
        names.extend(("tool_groups", "expand_tools"))
        return [_spec_entry(n, _TOOLS[n]) for n in names]
    return [_spec_entry(name, spec) for name, spec in _TOOLS.items()]


def _call_tool(name: str, arguments: dict, service=None) -> dict:
    spec = _TOOLS.get(name)
    if spec is None:
        return {"error": f"未知工具: {name}"}
    for req in spec["required"]:
        if req not in arguments:
            return {"error": f"工具 {name} 缺少必填参数: {req}"}
    handler: Callable[[Any, dict], Any] = spec["handler"]
    return handler(service if service is not None else _default_service(), arguments)


def handle_request(req: dict, service=None) -> dict | None:
    """处理一条 JSON-RPC 请求；通知（无 id）返回 None。

    service 缺省用模块级 _SERVICE（stdio 形态）；HTTP /mcp 形态传入桥自身的
    进程内 BridgeService，与 /api/* 共享同一套会话/模式/工程态（线程安全：
    不改全局，逐请求显式传递）。"""
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
        try:
            payload = _call_tool(name, arguments, service)
        except Exception as exc:  # 处理器异常绝不掀翻整个 MCP 服务；如实降级为 isError
            payload = {"error": f"{type(exc).__name__}: {exc}"}
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
    # Windows 控制台默认区域码页（cp1252/GBK）：出向无法编码中文工具描述，入向把客户端
    # UTF-8 JSON 的中文参数（如 route 的 @句柄 中文动词）静默解成乱码。收发统一 UTF-8。
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
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
