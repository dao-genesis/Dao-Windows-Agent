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

import os
from typing import Any, Optional

from core.accounts import AccountManager
from core.adapter.base import ActionResult
from core.agent.modes import ModeManager
from core.clone import (
    CloneLifecycle,
    IsolationTier,
    isolation_matrix,
    resolve_isolation,
)
from core.desktop_router import DesktopRouter
from core.session_activator import SessionActivator, loopback_for
from core.dispatch import MentionRouter
from core.environment import EnvironmentManager, available_tiers
from core.handoff import HandoffFlow
from core.macros import MacroStore
from core.profiles.builtin import build_default_registry
from core.profiles.registry import ProfileRegistry
from core.session.manager import SessionManager


def _detect_cdp_bindings():
    """按显式环境变量 DAO_CDP_PORT 绑定本机 Chrome CDP。

    设置了 → 返回 (browser_factory, jlceda evaluator)：两者共享同一 CDP 浏览器
    实例，evaluator 以 await 语义求值 handler 返回的 JS 表达式（_EXTAPI_ROOT_ 多为异步 API）。
    未设置 → (None, None)，对应画像保持 dry-run（确定性：不隐式探测，
    避免测试/CI 因环境碰巧开着调试端口而行为漂移）。"""
    raw = os.environ.get("DAO_CDP_PORT", "").strip()
    if not raw:
        return None, None
    port = int(raw)
    # 显式设置了 DAO_CDP_PORT 即视为用户意图绑定：端口此刻不活也绑（工厂具备
    # 零配置自动拉起 + 断连重建能力），避免启动竞态把 browser 永久钉死在 dry-run。

    from core.profiles.builtin.browser import make_browser_factory

    factory = make_browser_factory(port)
    _holder: list = []

    def evaluator(js: str):
        if not _holder:
            _holder.append(factory())
        return _holder[0].eval(js, await_promise=True, timeout=60)

    return factory, evaluator


class BridgeService:
    """把 SessionManager + ProfileRegistry 暴露为路由无关的动作集合。"""

    def __init__(
        self,
        registry: Optional[ProfileRegistry] = None,
        manager: Optional[SessionManager] = None,
        root: Optional[str] = None,
        accounts: Optional[AccountManager] = None,
        modes: Optional[ModeManager] = None,
        clones: Optional[CloneLifecycle] = None,
        macros: Optional[MacroStore] = None,
        env: Optional[EnvironmentManager] = None,
    ) -> None:
        # 默认底座即绑定 vendored agentctl（语义优先·规避截图+点击）并自动发现子插件
        # （用户装了哪个领域子插件就自动多出哪一路 @ 工作层）；CI/无后端时静默退回。
        # 显式设置 DAO_CDP_PORT（guest 内 firstlogon 统一 9222；Web 版 EDA 走 29229/29230）
        # 才把 browser 画像与 jlceda 的 CDP evaluator 绑到真浏览器；未设置保持 dry-run（离线可校验）。
        if registry is None:
            factory, evaluator = _detect_cdp_bindings()
            registry = build_default_registry(
                discover_subplugins=True, bind_osctl=True,
                browser_factory=factory, cdp_evaluator=evaluator)
        self.registry = registry
        self.manager = manager or SessionManager(self.registry, root=root)
        root = self.manager.root
        self.accounts = accounts or AccountManager()
        self.router = MentionRouter(self.registry)
        self.modes = modes or ModeManager(self.registry)
        self.handoff = HandoffFlow(
            self.registry,
            root=os.path.join(os.path.dirname(os.path.abspath(root)), "projects"))
        # 分身生命周期治理（心跳+超时回收，对称于租约 TTL）与宏沉淀层（成功序列固化）。
        self.clones = clones or CloneLifecycle()
        self.macros = macros or MacroStore()
        # 任意环境适配门面：探测本机能力 → 裁定可用档位 → 选桌面路由 → 出配备计划。
        self.env = env or EnvironmentManager()
        # 桌面级会话经纪：把 env + accounts + 隧道 编排成「一窗一路完整桌面」（L2 固化，知情同意门禁）。
        self.desktop = DesktopRouter(env=self.env, accounts=self.accounts)
        # 会话激活层：把「一路账号」点亮成一路 Active 桌面（cmdkey 入库 → mstsc 回环拉起 → qwinsta → logoff）。
        self.session_activator = SessionActivator()

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

    def _mode_denied(self, app_id: str) -> Optional[dict]:
        """模式工具面裁剪在调用面强制生效（如 coding 模式机控面关闭）。"""
        if app_id in self.modes.allowed_apps():
            return None
        mode = self.modes.current
        return {
            "ok": False, "value": None, "logs": [],
            "error": f"当前模式 {mode.mode_id}（{mode.name}）不开放应用 {app_id}"
                     f"（可用: {self.modes.allowed_apps()}）；先 /api/mode.set 切换模式",
        }

    def session_open_app(self, session_id: str, app_id: str, **kwargs: Any) -> dict:
        denied = self._mode_denied(app_id)
        if denied:
            return denied
        return _result_to_dict(self.manager.open_app(session_id, app_id, **kwargs))

    def session_invoke(
        self, session_id: str, app_id: str, verb: str, params: Optional[dict] = None
    ) -> dict:
        denied = self._mode_denied(app_id)
        if denied:
            return denied
        return _result_to_dict(
            self.manager.invoke(session_id, app_id, verb, **(params or {}))
        )

    def session_destroy(self, session_id: str) -> dict:
        return _result_to_dict(self.manager.destroy(session_id))

    def session_prompt(self, session_id: str) -> dict:
        """返回该会话当前应注入 Agent 的系统提示（模式覆盖 + 帛书纪律 + 已开软件纪律）。"""
        sess = self.manager.sessions.get(session_id)
        open_apps = sorted(sess.instances) if sess else []
        prompt = self.modes.build_prompt(open_apps)
        handoff = self.handoff.active_snippet()
        if handoff and self.modes.current.tool_policy != "none":
            prompt = prompt + "\n\n" + handoff
        return {
            "session_id": session_id,
            "mode": self.modes.current.mode_id,
            "prompt": prompt,
        }

    # --- 通用适配层 · @ 调度（AI 交互基底：一句自然语言 → 裁定通用层/领域工作层） ---
    def route(self, text: str, verb_limit: int = 5) -> dict:
        d = self.router.route(text or "", verb_limit=verb_limit)
        allowed = set(self.modes.allowed_apps())
        blocked = [t for t in d.targets if t not in allowed]
        targets = [t for t in d.targets if t in allowed]
        hints = [h for h in d.verb_hints if h.get("app_id") in allowed]
        out = {
            "targets": targets,
            "layer": d.layer,
            "unresolved": d.unresolved,
            "clean_text": d.clean_text,
            "verb_hints": hints,
            "mode": self.modes.current.mode_id,
        }
        if blocked:
            out["blocked_by_mode"] = blocked
            out["hint"] = (f"当前模式 {self.modes.current.mode_id} 不开放: {blocked}；"
                           "先 /api/mode.set 切换模式")
        return out

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

    # --- 工程交接（螺旋递进：领域工程完成后交接下一环节） ---
    def project_create(self, project_id: str, goal: str = "", stages: Optional[list] = None) -> dict:
        return self.handoff.create(project_id, goal, stages or [])

    def project_advance(self, project_id: str, artifacts: Optional[list] = None, note: str = "") -> dict:
        return self.handoff.advance(project_id, artifacts, note)

    def project_status(self, project_id: str) -> dict:
        return self.handoff.status(project_id)

    def project_list(self) -> dict:
        return self.handoff.list()

    # --- 账号（Windows 多账号类虚拟机·扩展本源） ---
    def account_create(self, name: str, password: Optional[str] = None, admin: bool = False) -> dict:
        return self.accounts.create(name, password=password, admin=admin)

    def account_list(self) -> dict:
        return self.accounts.list()

    def account_destroy(self, name: str, delete_profile: bool = True) -> dict:
        return self.accounts.destroy(name, delete_profile=delete_profile)

    def account_sessions(self) -> dict:
        return self.accounts.sessions()

    # --- 任意环境适配层（探测本机能力 → 裁定可用档位 → 桌面路由 → 配备计划） ---
    def env_report(self) -> dict:
        return self.env.report()

    def env_probe(self) -> dict:
        return self.env.probe().to_dict()

    def env_provision(self, apply: bool = False) -> dict:
        return self.env.provision(apply=bool(apply))

    # --- 桌面级会话经纪（一窗一路：探测→选路→授权后配备+建号→渲染描述符·可回滚） ---
    def desktop_plan(self, session_id: str, want: str = "desktop") -> dict:
        return self.desktop.plan(session_id, want=want)

    def desktop_ensure(self, session_id: str, approve_provision: bool = False,
                       approve_account: bool = False,
                       approve_activate: bool = False,
                       password: Optional[str] = None) -> dict:
        return self.desktop.ensure(
            session_id, approve_provision=bool(approve_provision),
            approve_account=bool(approve_account),
            approve_activate=bool(approve_activate), password=password)

    def desktop_status(self, session_id: str) -> dict:
        return self.desktop.status(session_id)

    def desktop_discover(self) -> dict:
        """只读发现真机已有的 account→loopback 映射。"""
        return self.desktop.discover_targets()

    def desktop_release(self, session_id: str, approve: bool = False,
                        delete_profile: bool = True) -> dict:
        return self.desktop.release(
            session_id, approve=bool(approve), delete_profile=bool(delete_profile))

    # --- 会话激活（把一路账号点亮成一路 Active 桌面·可逆） ---
    def rdp_session_list(self) -> dict:
        """真机当前所有会话（qwinsta：含 sessionname/id/state/active）。"""
        return self.session_activator.list_sessions()

    def rdp_session_activate(self, username: str, password: str, index: int,
                             approve: bool = False) -> dict:
        """凭据入库 + 回环拉起一路独立会话（写操作·受 approve 门禁）。

        index → 专属回环地址(127.0.0.2 起)。未授权即诚实返回 blocked，不动机器。
        """
        target = loopback_for(int(index))
        if not approve:
            return {"ok": False, "blocked": True, "username": username,
                    "target": target,
                    "reason": "激活将写入凭据管理器并拉起 RDP 会话，需 approve=true 明确同意。"}
        stored = self.session_activator.store_credential(target, username, password)
        if not stored.get("ok"):
            return {"ok": False, "stage": "store_credential", "detail": stored}
        launched = self.session_activator.activate(target)
        return {"ok": bool(launched.get("ok")), "username": username, "target": target,
                "stage": "activate", "detail": launched}

    def rdp_session_logoff(self, username: str = "", session_id: str = "",
                           approve: bool = False) -> dict:
        """注销会话（按账号名或会话ID·可逆清理·受 approve 门禁）。"""
        if not approve:
            return {"ok": False, "blocked": True,
                    "reason": "注销会话需 approve=true 明确同意。"}
        if session_id:
            return self.session_activator.logoff(str(session_id))
        if username:
            return self.session_activator.logoff_user(username)
        return {"ok": False, "error": "需提供 username 或 session_id"}

    def _auto_tiers(self, tiers: Optional[list]) -> Optional[list]:
        """tiers 未显式给定时，用本机探测出的**当前即可用**档位喂隔离层，
        实现「任意环境自动适配」——而非退回最悲观的零配置三档缺省。"""
        if tiers:
            return _parse_tiers(tiers)
        detected = available_tiers(self.env.probe())
        return sorted(detected)

    # --- 通用隔离层（单账号多分身：三机制归一选档，见 core/clone/isolation_layer） ---
    def clone_plan(self, app_id: str, clone_id: str,
                   tiers: Optional[list] = None, prefer_strongest: bool = False,
                   auto_detect: bool = False) -> dict:
        chosen = self._auto_tiers(tiers) if auto_detect else _parse_tiers(tiers)
        return resolve_isolation(
            app_id, clone_id, chosen, bool(prefer_strongest)).to_dict()

    def clone_matrix(self, app_ids: list,
                     tiers: Optional[list] = None, prefer_strongest: bool = False,
                     auto_detect: bool = False) -> dict:
        chosen = self._auto_tiers(tiers) if auto_detect else _parse_tiers(tiers)
        return {"matrix": isolation_matrix(
            app_ids, chosen, bool(prefer_strongest))}

    # --- 分身生命周期治理（clone_health 心跳 / clone_gc 超时回收，对称租约 TTL） ---
    def clone_register(self, clone_id: str, app_id: str, tier: str = "",
                       ttl: Optional[float] = None) -> dict:
        rec = self.clones.register(clone_id, app_id, tier=tier or "", ttl=ttl)
        return rec.to_dict()

    def clone_heartbeat(self, clone_id: str) -> dict:
        rec = self.clones.heartbeat(clone_id)
        if rec is None:
            return {"error": f"分身未登记: {clone_id}（先 clone_register）"}
        return rec.to_dict()

    def clone_health(self) -> dict:
        return self.clones.health()

    def clone_gc(self, dry_run: bool = False) -> dict:
        return self.clones.gc(dry_run=bool(dry_run))

    # --- 宏沉淀层（成功动词序列固化为新动词·经验沉淀） ---
    def macro_list(self) -> dict:
        return self.macros.list()

    def macro_get(self, name: str) -> dict:
        m = self.macros.get(name)
        return m if m is not None else {"error": f"无此宏: {name}"}

    def macro_save(self, name: str, steps: list, description: str = "") -> dict:
        return self.macros.save(name, steps or [], description)

    def macro_delete(self, name: str) -> dict:
        return self.macros.delete(name)

    def macro_run(self, name: str, session_id: str,
                  overrides: Optional[dict] = None) -> dict:
        def invoker(app_id: str, verb: str, params: dict) -> dict:
            return self.session_invoke(session_id, app_id, verb, params)

        norm = None
        if overrides:
            norm = {int(k): v for k, v in overrides.items()}
        return self.macros.run(name, invoker, overrides=norm)

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
            if method == "POST" and path == "/api/project.create":
                pid = _require(payload, "project_id")
                return 200, self.project_create(
                    pid, str(payload.get("goal") or ""),
                    payload.get("stages") or [])
            if method == "POST" and path == "/api/project.advance":
                pid = _require(payload, "project_id")
                return 200, self.project_advance(
                    pid, payload.get("artifacts"), str(payload.get("note") or ""))
            if method == "POST" and path == "/api/project.status":
                pid = _require(payload, "project_id")
                return 200, self.project_status(pid)
            if method == "GET" and path == "/api/project.list":
                return 200, self.project_list()
            if method == "GET" and path == "/api/env.report":
                return 200, self.env_report()
            if method == "GET" and path == "/api/env.probe":
                return 200, self.env_probe()
            if method == "POST" and path == "/api/env.provision":
                return 200, self.env_provision(bool(payload.get("apply", False)))
            if method == "POST" and path == "/api/desktop.plan":
                sid = _require(payload, "session_id")
                return 200, self.desktop_plan(sid, str(payload.get("want") or "desktop"))
            if method == "POST" and path == "/api/desktop.ensure":
                sid = _require(payload, "session_id")
                return 200, self.desktop_ensure(
                    sid, bool(payload.get("approve_provision", False)),
                    bool(payload.get("approve_account", False)),
                    bool(payload.get("approve_activate", False)),
                    payload.get("password"))
            if method == "POST" and path == "/api/desktop.status":
                sid = _require(payload, "session_id")
                return 200, self.desktop_status(sid)
            if method == "GET" and path == "/api/desktop.discover":
                return 200, self.desktop_discover()
            if method == "POST" and path == "/api/desktop.release":
                sid = _require(payload, "session_id")
                return 200, self.desktop_release(
                    sid, bool(payload.get("approve", False)),
                    bool(payload.get("delete_profile", True)))
            if method == "GET" and path == "/api/rdp.list":
                return 200, self.rdp_session_list()
            if method == "POST" and path == "/api/rdp.activate":
                return 200, self.rdp_session_activate(
                    _require(payload, "username"), _require(payload, "password"),
                    int(payload.get("index", 0)), bool(payload.get("approve", False)))
            if method == "POST" and path == "/api/rdp.logoff":
                return 200, self.rdp_session_logoff(
                    str(payload.get("username") or ""), str(payload.get("session_id") or ""),
                    bool(payload.get("approve", False)))
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
            if method == "POST" and path == "/api/clone.plan":
                app_id = _require(payload, "app_id")
                clone_id = _require(payload, "clone_id")
                return 200, self.clone_plan(
                    app_id, clone_id, payload.get("tiers"),
                    bool(payload.get("prefer_strongest", False)),
                    bool(payload.get("auto_detect", False)))
            if method == "POST" and path == "/api/clone.matrix":
                app_ids = _require(payload, "app_ids")
                return 200, self.clone_matrix(
                    list(app_ids), payload.get("tiers"),
                    bool(payload.get("prefer_strongest", False)),
                    bool(payload.get("auto_detect", False)))
            if method == "POST" and path == "/api/clone.register":
                clone_id = _require(payload, "clone_id")
                app_id = _require(payload, "app_id")
                return 200, self.clone_register(
                    clone_id, app_id, str(payload.get("tier") or ""),
                    payload.get("ttl"))
            if method == "POST" and path == "/api/clone.heartbeat":
                clone_id = _require(payload, "clone_id")
                return 200, self.clone_heartbeat(clone_id)
            if method == "GET" and path == "/api/clone.health":
                return 200, self.clone_health()
            if method == "POST" and path == "/api/clone.gc":
                return 200, self.clone_gc(bool(payload.get("dry_run", False)))
            if method == "GET" and path == "/api/macro.list":
                return 200, self.macro_list()
            if method == "POST" and path == "/api/macro.get":
                return 200, self.macro_get(_require(payload, "name"))
            if method == "POST" and path == "/api/macro.save":
                name = _require(payload, "name")
                return 200, self.macro_save(
                    name, payload.get("steps") or [], str(payload.get("description") or ""))
            if method == "POST" and path == "/api/macro.delete":
                return 200, self.macro_delete(_require(payload, "name"))
            if method == "POST" and path == "/api/macro.run":
                name = _require(payload, "name")
                sid = _require(payload, "session_id")
                return 200, self.macro_run(name, sid, payload.get("overrides"))
        except KeyError as exc:
            return 400, {"error": f"缺少必填参数: {exc.args[0]}"}
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - 边界统一兜底
            return 500, {"error": f"{type(exc).__name__}: {exc}"}
        return 404, {"error": f"未知路由: {method} {path}"}


def _parse_tiers(tiers: Optional[list]) -> Optional[list[IsolationTier]]:
    """把 ["appdata","session",...] 解析为档位集合；None/空 = 缺省零配置三档。"""
    if not tiers:
        return None
    by_label = {t.label: t for t in IsolationTier}
    out = []
    for raw in tiers:
        key = str(raw).strip().lower()
        if key not in by_label:
            raise ValueError(f"tiers 含未知档位: {raw}（可用: {sorted(by_label)}）")
        out.append(by_label[key])
    return out


def _require(payload: dict, key: str) -> Any:
    if key not in payload or payload[key] in (None, ""):
        raise KeyError(key)
    return payload[key]


def _result_to_dict(r: ActionResult) -> dict:
    return {"ok": r.ok, "value": r.value, "error": r.error, "logs": r.logs}
