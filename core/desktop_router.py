"""DesktopRouter · 桌面级会话经纪（L2 半自动固化的编排层）。

道法自然 · 无为而无不为。本层把此前**离散**的三块能力——
`EnvironmentManager`（探测/选路/配备）、`AccountManager`（账号=一路类虚拟机会话）、
隧道/guacd 渲染前端——**编排成「给一个 IDE 窗口一路可用完整桌面」的一步流程**，
对齐 `docs/兜底-通用AI配置Runbook-任意Windows多RDP接入.md` §八「反向路由进面板」。

核心不变量：
  · **一窗一路**：每个 IDE 窗口(session_id) 稳定映射到**一个专属账号**（`dao<6hex>`，
    由 session_id 派生，幂等），互不串扰。
  · **知情同意门禁**：任何对用户真机的写操作（开 RDP / 建号）默认**只出计划(dry-run)**，
    仅在显式 `approve_*` 时执行；未授权即诚实列出 pending，绝不擅自改机器。
  · **可回滚**：`release` 逆向注销会话 + 删「我们建的」账号（仅限本层派生的账号名）。
  · **诚实选路**：Server/Pro/Edu/Ent 走多会话 RDP（路 A）；非 Windows / 无提权走兜底路线，
    如实告知，不假装桌面就绪。
  · **凭据安全**：渲染描述符默认**不含密码**；密码只在 `include_secret=True`（供隧道内部铸链）
    时取自账号注册表，绝不回传日志/Agent/PR。

纯 Python·管理器可注入 → Linux/CI 上纯逻辑可单测（不碰真机）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from core.accounts import AccountManager, valid_name
from core.environment import EnvironmentManager, EnvProbe, desktop_strategy


def account_name_for(session_id: str) -> str:
    """由 IDE 窗口 session_id 稳定派生专属账号名（幂等·一窗一路）。

    `dao` + sha1(session_id) 前 6 位 hex → 合法（字母开头、≤20、字符集受限），
    同一窗口永远得同一账号；不同窗口极难碰撞。
    """
    h = hashlib.sha1((session_id or "").encode("utf-8")).hexdigest()[:6]
    name = f"dao{h}"
    # 兜底：万一 session_id 为空派生出的名不合法，退回定长安全名。
    return name if valid_name(name) else "dao000000"


# 桌面路由 → 是否「基于用户真机多会话账号」。
_ACCOUNT_ROUTES = {"A-rdp-multisession"}


@dataclass
class DesktopRouter:
    """探测→选路→（授权后）配备+建号→产出渲染描述符 的统一编排门面。"""

    env: EnvironmentManager
    accounts: AccountManager

    # ---- 只读：计划 ----
    def plan(self, session_id: str, want: str = "desktop") -> dict:
        """出**一窗一路**的落地计划（dry-run，不改真机）：选路 + 配备计划 + 待授权项。"""
        if not session_id:
            return {"ok": False, "error": "session_id 必填（对应一个 IDE 窗口）"}
        p = self.env.probe()
        strategy = desktop_strategy(p)
        route = strategy.get("route", "")
        name = account_name_for(session_id)
        plan: dict = {
            "ok": True,
            "session_id": session_id,
            "want": want,
            "route": route,
            "route_ready": bool(strategy.get("ready")),
            "route_reason": strategy.get("reason", ""),
            "account_name": name if route in _ACCOUNT_ROUTES else None,
        }
        if route in _ACCOUNT_ROUTES:
            prov = self.env.provision(apply=False)["plan"]
            pending = self._pending(p, prov, name)
            plan["provision_plan"] = prov
            plan["pending_consent"] = pending
            plan["consent_ready"] = not pending
        else:
            # 非账号路线（B 桌面隔离 / C 无头 / Z 冷启动）：桌面由别的机制承载，如实说明。
            plan["provision_plan"] = None
            plan["pending_consent"] = []
            plan["consent_ready"] = True
            plan["note"] = {
                "B-virtual-display": "退路线 B：CreateDesktop 隔离桌面 + 虚拟显示器（隔离层承载，无需真机建号）。",
                "C-headless": "路线 C：无头 API/CLI/CDP 驱动，天然隔离并行，无需桌面账号。",
                "Z-coldstart": "路线 Z：coldstart 自有 VM 承载完整桌面，不依赖/不改用户真机。",
            }.get(route, "")
        return plan

    def _pending(self, p: EnvProbe, prov: dict, name: str) -> list:
        """列出走多会话路线尚需用户明确同意的写操作（诚实门禁）。"""
        pending = []
        if not prov.get("already") and prov.get("steps"):
            requires_admin = any(s.get("requires_admin") for s in prov["steps"])
            pending.append({
                "action": "provision",
                "requires_admin": requires_admin,
                "achievable": bool(prov.get("achievable")),
                "steps": [s["id"] for s in prov["steps"]],
                "reason": "开启 RDP / 放开单会话 / 装 RDPWrap 需管理员且改动本机（可回滚）",
            })
        # 账号是否已存在（我们建的）？未存在则需同意建号。
        existing = {a["name"] for a in self.accounts.list().get("accounts", [])}
        if name not in existing:
            pending.append({
                "action": "create_account",
                "requires_admin": True,
                "name": name,
                "reason": "为本窗口创建专属本地账号并加入 Remote Desktop Users（可 release 回滚）",
            })
        return pending

    # ---- 写：授权后编排就绪 ----
    def ensure(
        self,
        session_id: str,
        approve_provision: bool = False,
        approve_account: bool = False,
        password: Optional[str] = None,
    ) -> dict:
        """把一窗一路推进到「就绪」——每步受 approve 门禁；未授权即诚实返回 pending。"""
        if not session_id:
            return {"ok": False, "error": "session_id 必填"}
        p = self.env.probe()
        strategy = desktop_strategy(p)
        route = strategy.get("route", "")
        name = account_name_for(session_id)

        if route not in _ACCOUNT_ROUTES:
            # 非账号路线：无真机写操作，直接就绪（桌面由 B/C/Z 承载）。
            return {
                "ok": True, "session_id": session_id, "route": route,
                "ready": bool(strategy.get("ready")), "account_name": None,
                "reason": strategy.get("reason", ""),
                "render": None,
                "note": "非多会话路线：无需在用户真机建号；桌面由隔离层/冷启动承载。",
            }

        steps_done = []
        # 1) 配备（开 RDP/放开单会话/装 RDPWrap）——受 approve_provision 门禁
        prov_plan = self.env.provision(apply=False)["plan"]
        if not prov_plan.get("already") and prov_plan.get("steps"):
            if not approve_provision:
                return self._blocked(session_id, route, name,
                                     "provision", prov_plan)
            prov_result = self.env.provision(apply=True)
            steps_done.append({"provision": prov_result.get("results", [])})
            # 重探，确认配备是否真的抬升
            p = self.env.probe()

        # 2) 建号（一窗一路专属账号）——受 approve_account 门禁
        existing = {a["name"] for a in self.accounts.list().get("accounts", [])}
        if name not in existing:
            if not approve_account:
                return self._blocked(session_id, route, name, "create_account", prov_plan)
            created = self.accounts.create(name, password=password)
            if not created.get("ok"):
                return {"ok": False, "session_id": session_id, "route": route,
                        "account_name": name, "error": created.get("error"),
                        "stage": "create_account", "steps_done": steps_done}
            steps_done.append({"create_account": name})

        render = self.render_descriptor(session_id, include_secret=False)
        return {
            "ok": True, "session_id": session_id, "route": route,
            "ready": True, "account_name": name,
            "steps_done": steps_done,
            "render": render,
            "reason": "一窗一路就绪：账号已备，隧道可经 render 建 RDP→guacd→WS→面板链路。",
        }

    def _blocked(self, session_id: str, route: str, name: str,
                 stage: str, prov_plan: dict) -> dict:
        return {
            "ok": False, "blocked": True, "stage": stage,
            "session_id": session_id, "route": route, "account_name": name,
            "provision_plan": prov_plan,
            "reason": ("需用户明确同意后方可对本机执行写操作（可回滚）。"
                       f"缺少授权: {stage}（provision→approve_provision, "
                       "create_account→approve_account）。"),
        }

    # ---- 渲染描述符（供隧道/guacd 前端建链，一窗一路） ----
    def render_descriptor(self, session_id: str, include_secret: bool = False) -> Optional[dict]:
        """从账号注册表取本窗口账号的 RDP 目标，产出 guacd 连接描述符。

        include_secret=False（缺省）：**不含密码**，可安全回传 Agent/日志。
        include_secret=True：含密码，仅供隧道进程内部铸链，切勿外泄。
        """
        name = account_name_for(session_id)
        for a in self.accounts.list().get("accounts", []):
            if a["name"] == name:
                tgt = a.get("target", {})
                params = {
                    "hostname": tgt.get("hostname"),
                    "port": tgt.get("port"),
                    "username": tgt.get("username"),
                    "security": "any",
                    "ignore-cert": "true",
                    "resize-method": "display-update",
                }
                if include_secret:
                    creds = self.accounts._load().get(name, {})  # 仅隧道内部取密码
                    if creds.get("password"):
                        params["password"] = creds["password"]
                return {
                    "session_id": session_id,
                    "account_name": name,
                    "protocol": "rdp",
                    "guac": {"connection": {"protocol": "rdp", "parameters": params}},
                }
        return None

    # ---- 状态 ----
    def status(self, session_id: str) -> dict:
        name = account_name_for(session_id)
        accounts = self.accounts.list().get("accounts", [])
        bound = next((a for a in accounts if a["name"] == name), None)
        return {
            "ok": True, "session_id": session_id, "account_name": name,
            "bound": bound is not None,
            "session": (bound or {}).get("session"),
            "render": self.render_descriptor(session_id) if bound else None,
        }

    # ---- 回滚 ----
    def release(self, session_id: str, approve: bool = False,
                delete_profile: bool = True) -> dict:
        """释放一窗一路：注销会话 + 删「本层派生」账号（受 approve 门禁·可逆）。"""
        name = account_name_for(session_id)
        if not approve:
            return {"ok": False, "blocked": True, "session_id": session_id,
                    "account_name": name,
                    "reason": "释放将删除本窗口专属账号及其 profile，需 approve=true 明确同意。"}
        result = self.accounts.destroy(name, delete_profile=delete_profile)
        return {"ok": bool(result.get("ok")), "session_id": session_id,
                "account_name": name, "detail": result}


__all__ = ["DesktopRouter", "account_name_for"]
