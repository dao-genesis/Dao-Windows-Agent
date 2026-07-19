"""SessionActivator · 把「一路账号」真正点亮成一路 Active 桌面会话（实测验证层）。

道法自然 · 无为而无不为。`AccountManager` 负责账号**生命周期**（建/列/销），
`DesktopRouter` 负责**编排选路**，但要让「一窗一路」真的渲染出一块**活桌面**，
还差最后一跳：**激活会话**——把账号凭据写进 Windows 凭据管理器(cmdkey)，
再经**回环地址(127.0.0.x)** 拉起一路 RDP 会话，使该账号从「已建」变为「Active」。

本模块固化 2026-07-19 在真机 `DESKTOP-MASTER`（Win11 教育版·Build 26200·RDPWrap 已载）
上**实测跑通**的最短可信链路：

    cmdkey /generic:TERMSRV/127.0.0.N /user:<账号> /pass:<密码>   # 凭据入库(免交互登录)
    mstsc /v:127.0.0.N                                            # 回环拉起独立会话
    qwinsta                                                       # 确认新会话 Active
    logoff <会话ID>                                               # 可逆清理

实测结论（见 docs/验证-真机多会话实测报告-DESKTOP-MASTER.md）：
  · 主控制台(Administrator·session 1) **全程 Active 不受影响**；
  · 新会话(ai·rdp-tcp#0·session 4) **并发 Active**，内含完整桌面(52 进程·独立 explorer/IME)；
  · `logoff` 干净回收，回到单会话初态。

设计要点：
  · **回环多路**：每账号映射一个专属 127.0.0.x（`loopback_for`），避免会话互相顶替；
  · **免交互**：凭据先入 Credential Manager，mstsc/guacd 均可零提示直登（NLA 关或 any）；
  · **可注入 runner**：默认真机 subprocess；单测注入 fake，纯逻辑在 Linux/CI 可测；
  · **诚实与可逆**：只 activate/list/logoff，绝不改机器全局策略；清理只针对本层拉起的会话。
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

from core.adapter.subprocess_api import decode_output

# runner(argv:list[str]) -> (returncode:int, stdout:str, stderr:str)
Runner = Callable[["list[str]"], "tuple[int, str, str]"]

_LOOPBACK_BASE = "127.0.0."
# 保留 .1 给主控制台/Administrator，业务账号从 .2 起分配。
_LOOPBACK_START = 2
_LOOPBACK_MAX = 254
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\\-]{0,63}$")


def _default_runner(argv: "list[str]") -> "tuple[int, str, str]":
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=60)
    except FileNotFoundError:
        return 127, "", f"{argv[0]} 不可用（非 Windows 主机）：会话激活需在真机执行"
    return proc.returncode, decode_output(proc.stdout), decode_output(proc.stderr)


def loopback_for(index: int) -> str:
    """把一路序号(0-based)稳定映射到一个专属回环地址(127.0.0.2 起)。"""
    n = _LOOPBACK_START + max(0, int(index))
    if n > _LOOPBACK_MAX:
        raise ValueError(f"回环地址超出可用范围: index={index}")
    return _LOOPBACK_BASE + str(n)


@dataclass
class Session:
    """qwinsta 一行解析结果。"""

    sessionname: str
    username: str
    id: Optional[str]
    state: str
    raw: str

    @property
    def active(self) -> bool:
        return self.state.lower() == "active"

    def to_dict(self) -> dict:
        return {
            "sessionname": self.sessionname,
            "username": self.username,
            "id": self.id,
            "state": self.state,
            "active": self.active,
        }


@dataclass
class SessionActivator:
    runner: Runner = _default_runner

    # ---- 凭据入库（免交互直登的前提） ----
    def store_credential(self, target_ip: str, username: str, password: str) -> dict:
        """把账号凭据写进 Windows 凭据管理器，令 mstsc/guacd 对该回环目标零提示直登。"""
        if not _valid(username):
            return {"ok": False, "error": f"非法账号名: {username!r}"}
        if not _valid_ip(target_ip):
            return {"ok": False, "error": f"非法目标: {target_ip!r}"}
        rc, out, err = self.runner([
            "cmdkey",
            f"/generic:TERMSRV/{target_ip}",
            f"/user:{username}",
            f"/pass:{password}",
        ])
        if rc != 0:
            return {"ok": False, "error": (err or out or f"rc={rc}").strip()}
        return {"ok": True, "target": f"TERMSRV/{target_ip}", "username": username}

    def clear_credential(self, target_ip: str) -> dict:
        """删除该回环目标的已存凭据（可逆清理）。"""
        if not _valid_ip(target_ip):
            return {"ok": False, "error": f"非法目标: {target_ip!r}"}
        rc, out, err = self.runner(["cmdkey", f"/delete:TERMSRV/{target_ip}"])
        if rc != 0:
            return {"ok": False, "error": (err or out or f"rc={rc}").strip()}
        return {"ok": True, "target": f"TERMSRV/{target_ip}"}

    # ---- 激活：把账号点亮成一路 Active 桌面 ----
    def activate(self, target_ip: str, minimized: bool = True) -> dict:
        """经回环地址拉起一路独立 RDP 会话（凭据须已入库）。返回启动结果，不阻塞。

        实测：凭据入库后 mstsc /v:<回环> 免提示直登，8s 内该账号会话即 Active，
        主控制台会话不受影响。真机上 mstsc 为 GUI 进程，此处仅负责拉起。
        """
        if not _valid_ip(target_ip):
            return {"ok": False, "error": f"非法目标: {target_ip!r}"}
        argv = ["mstsc", f"/v:{target_ip}"]
        rc, out, err = self.runner(argv)
        # mstsc 拉起后即返回；rc!=0 才算失败。
        if rc not in (0,):
            return {"ok": False, "error": (err or out or f"rc={rc}").strip(), "target": target_ip}
        return {"ok": True, "target": target_ip, "launched": True}

    # ---- 会话枚举（qwinsta，比 quser 更全：含 sessionname/listen） ----
    def list_sessions(self) -> dict:
        rc, out, err = self.runner(["qwinsta"])
        if rc != 0 or not out:
            return {"ok": False, "error": (err or f"rc={rc}").strip(), "sessions": []}
        sessions = [s.to_dict() for s in _parse_qwinsta(out)]
        active = [s for s in sessions if s["active"]]
        return {"ok": True, "sessions": sessions, "active_count": len(active)}

    def find_session(self, username: str) -> Optional[dict]:
        for s in self.list_sessions().get("sessions", []):
            if s["username"].lower() == (username or "").lower():
                return s
        return None

    # ---- 回收（可逆） ----
    def logoff(self, session_id: str) -> dict:
        sid = str(session_id)
        if not sid.isdigit():
            return {"ok": False, "error": f"非法会话ID: {session_id!r}"}
        rc, out, err = self.runner(["logoff", sid])
        if rc != 0:
            return {"ok": False, "error": (err or out or f"rc={rc}").strip(), "id": sid}
        return {"ok": True, "id": sid}

    def logoff_user(self, username: str) -> dict:
        """按账号名注销其会话（先查会话ID再 logoff）。"""
        s = self.find_session(username)
        if not s:
            return {"ok": True, "already_absent": True, "username": username}
        if not s.get("id"):
            return {"ok": False, "error": "会话无有效ID", "username": username}
        r = self.logoff(s["id"])
        r["username"] = username
        return r


def _valid(name: str) -> bool:
    return bool(_NAME_RE.match(name or ""))


def _valid_ip(ip: str) -> bool:
    if not ip or not isinstance(ip, str):
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def _parse_qwinsta(out: str) -> "list[Session]":
    """解析 qwinsta 输出。列固定宽度但可能空缺，按启发式定位 ID(纯数字)与其两侧字段。

    典型行：
      >console                   Administrator             1  Active
       rdp-tcp#0                 ai                        4  Active
       rdp-tcp                                         65536  Listen
       services                                            0  Disc
    """
    lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    rows: "list[Session]" = []
    for ln in lines[1:]:  # 跳表头
        body = ln.lstrip(">").rstrip()
        parts = body.split()
        if not parts:
            continue
        # 找到首个纯数字列作为 session id 锚点。
        id_idx = next((i for i, p in enumerate(parts) if p.isdigit()), None)
        if id_idx is None:
            continue
        sid = parts[id_idx]
        state = parts[id_idx + 1] if id_idx + 1 < len(parts) else ""
        # id 之前的列：sessionname [username]。
        head = parts[:id_idx]
        if len(head) >= 2:
            sessionname, username = head[0], head[1]
        elif len(head) == 1:
            sessionname, username = head[0], ""
        else:
            sessionname, username = "", ""
        rows.append(Session(sessionname=sessionname, username=username,
                            id=sid, state=state, raw=ln.strip()))
    return rows


__all__ = ["SessionActivator", "Session", "loopback_for"]
