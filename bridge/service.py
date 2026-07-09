"""BridgeService：机控桥的纯逻辑核心（无 socket、无第三方依赖，可直接单测）。

沿用 bridge/README.md 的暴露约定（REST 内核 + MCP 外壳共用同一 service）：

    POST /api/session.create     {session_id?}            -> {session_id, workdir}
    POST /api/session.open_app   {session_id, app_id}     -> {session_id, app_id, workdir}
    POST /api/session.invoke     {session_id, app_id, verb, params?} -> {ok, value, error, logs}
    POST /api/session.destroy    {session_id}             -> {destroyed}
    GET  /api/session.list                                 -> {sessions:[...]}
    GET  /api/apps                                          -> {apps:[...]}
    POST /api/describe_app       {app_id}                  -> {...profile...}   (ha-copilot describe_tool 配方)
    POST /api/search_verbs       {query, limit?}           -> {hits:[...]}      (ha-copilot search_tools 配方)
    GET  /api/health                                        -> {ok, apps, sessions}

MCP 外壳把上述动作包成工具，任意 Agent（Devin/Claude/本插件）即插即用。
"""
from __future__ import annotations

from typing import Any, Optional

from core.accounts import AccountManager
from core.adapter.base import ActionResult
from core.agent.modes import ModeManager
from core.dispatch import MentionRouter
from core.profiles.builtin import build_default_registry
from core.profiles.registry import ProfileRegistry
from core.session.manager import SessionManager


class BridgeService:
    """把 SessionManager + ProfileRegistry 暴露为路由无关的动作集合。"""

    def __init__(
        self,
        registry: Optional[ProfileRegistry] = None,
        manager: Optional[SessionManager] = None,
        root: str = "/tmp/dao-win/sessions",
        accounts: Optional[AccountManager] = None,
        modes: Optional[ModeManager] = None,
    ) -> None:
        # 默认底座即绑定 vendored agentctl（语义优先·规避截图+点击）并自动发现子插件
        # （用户装了哪个领域子插件就自动多出哪一路 @ 工作层）；CI/无后端时静默退回。
        self.registry = registry or build_default_registry(
            discover_subplugins=True, bind_osctl=True)
        self.manager = manager or SessionManager(self.registry, root=root)
        self.accounts = accounts or AccountManager()
        self.router = MentionRouter(self.registry)
        self.modes = modes or ModeManager(self.registry)

    # --- 动作（被 REST / MCP 共用） ---
    def health(self) -> dict:
        return {
            "ok": True,
            "apps": self.registry.app_ids(),
            "sessions": self.manager.list(),
            "creed": "无为而无不为 · 道法自然",
        }

    def apps(self) -> dict:
        return {"apps": self.registry.app_ids()}

    def describe_app(self, app_id: str) -> dict:
        info = self.registry.describe_app(app_id)
        if info is None:
            return {"error": f"无此应用画像: {app_id}（可用: {self.registry.app_ids()}）"}
        return info

    def search_verbs(self, query: str, limit: int = 10) -> dict:
        return {"hits": self.registry.search_verbs(query, limit=limit)}

    def session_create(self, session_id: Optional[str] = None) -> dict:
        sess = self.manager.create(session_id)
        return {"session_id": sess.session_id, "workdir": sess.workdir}

    def session_list(self) -> dict:
        out = []
        for sid in self.manager.list():
            sess = self.manager.sessions[sid]
            out.append({"session_id": sid, "apps": sorted(sess.instances)})
        return {"sessions": out}

    def session_open_app(self, session_id: str, app_id: str, **kwargs: Any) -> dict:
        return _result_to_dict(self.manager.open_app(session_id, app_id, **kwargs))

    def session_invoke(
        self, session_id: str, app_id: str, verb: str, params: Optional[dict] = None
    ) -> dict:
        return _result_to_dict(
            self.manager.invoke(session_id, app_id, verb, **(params or {}))
        )

    def session_destroy(self, session_id: str) -> dict:
        return _result_to_dict(self.manager.destroy(session_id))

    def session_prompt(self, session_id: str) -> dict:
        """返回该会话当前应注入 Agent 的系统提示（模式覆盖 + 帛书纪律 + 已开软件纪律）。"""
        sess = self.manager.sessions.get(session_id)
        open_apps = sorted(sess.instances) if sess else []
        return {
            "session_id": session_id,
            "mode": self.modes.current.mode_id,
            "prompt": self.modes.build_prompt(open_apps),
        }

    # --- 通用适配层 · @ 调度（AI 交互基底：一句自然语言 → 裁定通用层/领域工作层） ---
    def route(self, text: str, verb_limit: int = 5) -> dict:
        d = self.router.route(text or "", verb_limit=verb_limit)
        return {
            "targets": d.targets,
            "layer": d.layer,
            "unresolved": d.unresolved,
            "clean_text": d.clean_text,
            "verb_hints": d.verb_hints,
        }

    def capabilities(self) -> dict:
        manifest = self.router.capability_manifest()
        scoped = self.modes.capabilities()
        manifest.update(scoped)
        return manifest

    # --- 模式切换层（三插件融合的枢纽：提示词覆盖 + 工具面裁剪） ---
    def mode_list(self) -> dict:
        return {
            "modes": [m.describe() for m in self.modes.modes()],
            "current": self.modes.current.mode_id,
        }

    def mode_get(self) -> dict:
        return {"current": self.modes.current.describe(),
                "allowed_apps": self.modes.allowed_apps()}

    def mode_set(self, mode_id: str) -> dict:
        try:
            mode = self.modes.set(mode_id)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"current": mode.describe(), "allowed_apps": self.modes.allowed_apps()}

    # --- 账号（Windows 多账号类虚拟机·扩展本源） ---
    def account_create(self, name: str, password: Optional[str] = None, admin: bool = False) -> dict:
        return self.accounts.create(name, password=password, admin=admin)

    def account_list(self) -> dict:
        return self.accounts.list()

    def account_destroy(self, name: str, delete_profile: bool = True) -> dict:
        return self.accounts.destroy(name, delete_profile=delete_profile)

    def account_sessions(self) -> dict:
        return self.accounts.sessions()

    # --- REST 路由分发（纯函数，便于单测） ---
    def dispatch(self, method: str, path: str, payload: Optional[dict] = None) -> tuple[int, dict]:
        payload = payload or {}
        method = method.upper()
        try:
            if method == "GET" and path == "/api/health":
                return 200, self.health()
            if method == "GET" and path == "/api/apps":
                return 200, self.apps()
            if method == "GET" and path == "/api/session.list":
                return 200, self.session_list()
            if method == "POST" and path == "/api/describe_app":
                app_id = _require(payload, "app_id")
                return 200, self.describe_app(app_id)
            if method == "POST" and path == "/api/search_verbs":
                query = _require(payload, "query")
                return 200, self.search_verbs(query, int(payload.get("limit", 10)))
            if method == "POST" and path == "/api/session.create":
                return 200, self.session_create(payload.get("session_id"))
            if method == "POST" and path == "/api/session.open_app":
                sid = _require(payload, "session_id")
                app_id = _require(payload, "app_id")
                extra = {k: v for k, v in payload.items() if k not in ("session_id", "app_id")}
                return 200, self.session_open_app(sid, app_id, **extra)
            if method == "POST" and path == "/api/session.invoke":
                sid = _require(payload, "session_id")
                app_id = _require(payload, "app_id")
                verb = _require(payload, "verb")
                return 200, self.session_invoke(sid, app_id, verb, payload.get("params"))
            if method == "POST" and path == "/api/session.destroy":
                sid = _require(payload, "session_id")
                return 200, self.session_destroy(sid)
            if method == "POST" and path == "/api/session.prompt":
                sid = _require(payload, "session_id")
                return 200, self.session_prompt(sid)
            if method == "POST" and path == "/api/route":
                text = _require(payload, "text")
                return 200, self.route(text, int(payload.get("verb_limit", 5)))
            if method == "GET" and path == "/api/capabilities":
                return 200, self.capabilities()
            if method == "GET" and path == "/api/mode.list":
                return 200, self.mode_list()
            if method == "GET" and path == "/api/mode.get":
                return 200, self.mode_get()
            if method == "POST" and path == "/api/mode.set":
                mode_id = _require(payload, "mode")
                return 200, self.mode_set(mode_id)
            if method == "GET" and path == "/api/account.list":
                return 200, self.account_list()
            if method == "GET" and path == "/api/account.sessions":
                return 200, self.account_sessions()
            if method == "POST" and path == "/api/account.create":
                name = _require(payload, "name")
                return 200, self.account_create(
                    name, payload.get("password"), bool(payload.get("admin", False)))
            if method == "POST" and path == "/api/account.destroy":
                name = _require(payload, "name")
                return 200, self.account_destroy(
                    name, bool(payload.get("delete_profile", True)))
        except KeyError as exc:
            return 400, {"error": f"缺少必填参数: {exc.args[0]}"}
        except Exception as exc:  # noqa: BLE001 - 边界统一兜底
            return 500, {"error": f"{type(exc).__name__}: {exc}"}
        return 404, {"error": f"未知路由: {method} {path}"}


def _require(payload: dict, key: str) -> Any:
    if key not in payload or payload[key] in (None, ""):
        raise KeyError(key)
    return payload[key]


def _result_to_dict(r: ActionResult) -> dict:
    return {"ok": r.ok, "value": r.value, "error": r.error, "logs": r.logs}
