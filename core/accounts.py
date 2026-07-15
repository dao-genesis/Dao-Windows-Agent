"""AccountManager · Windows 多账号类虚拟机内核（正本清源·扩展本源第七节）。

把"用户 Windows 上的每一个账号"当成一路类虚拟机：创建 / 列举 / 销毁子账号，
每账号一路独立完整桌面（经 RDPWrap 单机多会话并行、互不干扰）。这是把插件
"彻底对齐 Windows 多 RDP 全体系"的账号生命周期底座，复用 devin-remote/cloud/
vm-replica 的 New-LocalUser + Remote Desktop Users + RDPWrap 结论。

设计要点（可在 Linux 上单测）：
  · PowerShell 执行经**可注入的 runner**（默认真机 subprocess；单测注入 fake）。
  · 账号注册表持久化为 JSON（names + RDP 目标/凭据），**隧道 server.js 直接读同一份**
    用于按账号铸造 token —— Python(桥) 建号、Node(隧道) 路由，同一真相源。
  · 幂等：重复 create 已存在账号即更新组/凭据；destroy 不存在账号返回 already_absent。

账号注册表 JSON 形状（默认 desktop/accounts.json）：
  {
    "dao":  {"hostname":"127.0.0.1","port":"13389","username":"dao","password":"..."},
    "vm01": {"hostname":"127.0.0.1","port":"13389","username":"vm01","password":"..."}
  }
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.adapter.subprocess_api import decode_output

# runner(script:str) -> (returncode:int, stdout:str, stderr:str)
Runner = Callable[[str], "tuple[int, str, str]"]

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = "13389"
_DEFAULT_PASSWORD = "Dao@2026!"
# 账号名约束：字母数字与 . _ -，1..20，禁止前导保留字，防注入。
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$")


def _powershell_runner(script: str) -> "tuple[int, str, str]":
    """默认真机 runner：走 powershell -NoProfile -Command。仅 Windows 有效。"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=120,
        )
    except FileNotFoundError:
        return 127, "", "powershell 不可用（非 Windows 主机）：账号档位需在真机 Windows 上执行"
    return proc.returncode, decode_output(proc.stdout), decode_output(proc.stderr)


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or ""))


@dataclass
class AccountManager:
    runner: Runner = _powershell_runner
    registry_path: str = field(
        default_factory=lambda: os.environ.get(
            "DAO_ACCOUNTS_JSON",
            os.path.join(os.path.dirname(__file__), "..", "desktop", "accounts.json"),
        )
    )
    default_password: str = _DEFAULT_PASSWORD
    rdp_host: str = _DEFAULT_HOST
    rdp_port: str = _DEFAULT_PORT

    # ---- 注册表读写（隧道与桥共享的同一真相源） ----
    def _load(self) -> dict:
        try:
            if os.path.exists(self.registry_path):
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except (OSError, ValueError):
            pass
        return {}

    def _save(self, reg: dict) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.registry_path)), exist_ok=True)
        tmp = self.registry_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.registry_path)

    def _register(self, name: str, password: str) -> dict:
        reg = self._load()
        reg[name] = {
            "hostname": self.rdp_host,
            "port": self.rdp_port,
            "username": name,
            "password": password,
        }
        self._save(reg)
        return reg[name]

    def _unregister(self, name: str) -> None:
        reg = self._load()
        if name in reg:
            del reg[name]
            self._save(reg)

    # ---- 账号生命周期 ----
    def create(self, name: str, password: Optional[str] = None, admin: bool = False) -> dict:
        """创建（或幂等更新）本地账号并加入 Remote Desktop Users，登记进注册表。"""
        if not valid_name(name):
            return {"ok": False, "error": f"非法账号名: {name!r}（限字母数字与 . _ -，≤20）"}
        password = password or self.default_password
        groups = "Remote Desktop Users"
        script = _PS_CREATE.format(
            name=_ps_quote(name), password=_ps_quote(password),
            admin=("$true" if admin else "$false"),
        )
        rc, out, err = self.runner(script)
        if rc != 0:
            return {"ok": False, "error": (err or out or f"rc={rc}").strip(), "name": name}
        target = self._register(name, password)
        return {"ok": True, "name": name, "groups": [groups] + (["Administrators"] if admin else []),
                "target": {k: v for k, v in target.items() if k != "password"}}

    def list(self) -> dict:
        """列举账号：合并注册表（我们创建的）+ 真机会话态（quser）。"""
        reg = self._load()
        sessions = self._sessions_map()
        accounts = []
        for name, tgt in reg.items():
            accounts.append({
                "name": name,
                "target": {k: v for k, v in tgt.items() if k != "password"},
                "session": sessions.get(name.lower()),
            })
        return {"ok": True, "accounts": accounts}

    def destroy(self, name: str, delete_profile: bool = True) -> dict:
        """注销会话 + 删账号（可选删 profile），并从注册表摘除。"""
        if not valid_name(name):
            return {"ok": False, "error": f"非法账号名: {name!r}"}
        script = _PS_DESTROY.format(
            name=_ps_quote(name),
            delprofile=("$true" if delete_profile else "$false"),
        )
        rc, out, err = self.runner(script)
        self._unregister(name)
        if rc != 0:
            return {"ok": False, "error": (err or out or f"rc={rc}").strip(), "name": name}
        return {"ok": True, "name": name, "deleted_profile": delete_profile}

    def sessions(self) -> dict:
        """真机当前 RDP/控制台会话（quser 解析）。"""
        return {"ok": True, "sessions": self._sessions_raw()}

    def _sessions_raw(self) -> list:
        rc, out, _ = self.runner("quser")
        if rc != 0 or not out:
            return []
        return _parse_quser(out)

    def _sessions_map(self) -> dict:
        m = {}
        for s in self._sessions_raw():
            m[s["username"].lower()] = s
        return m


def _ps_quote(s: str) -> str:
    """单引号包裹 + PowerShell 单引号转义（'' ），配合名字白名单，杜绝注入。"""
    return "'" + str(s).replace("'", "''") + "'"


def _parse_quser(out: str) -> list:
    """解析 quser 输出为 [{username, session, id, state}]。容忍列错位。"""
    lines = [ln for ln in out.splitlines() if ln.strip()]
    rows = []
    for ln in lines[1:]:  # 跳表头
        parts = ln.split()
        if not parts:
            continue
        uname = parts[0].lstrip(">")
        # 尽量抓 ID（首个纯数字列）与 state（数字后一列）
        sid = None
        state = None
        for i, p in enumerate(parts[1:], start=1):
            if p.isdigit():
                sid = p
                state = parts[i + 1] if i + 1 < len(parts) else None
                break
        rows.append({"username": uname, "id": sid, "state": state, "raw": ln.strip()})
    return rows


# —— PowerShell 脚本模板（管理员上下文执行） ——
_PS_CREATE = r"""
$ErrorActionPreference='Stop'
$pw = ConvertTo-SecureString {password} -AsPlainText -Force
$u = Get-LocalUser -Name {name} -ErrorAction SilentlyContinue
if ($null -eq $u) {{
  New-LocalUser -Name {name} -Password $pw -PasswordNeverExpires -AccountNeverExpires | Out-Null
}} else {{
  Set-LocalUser -Name {name} -Password $pw
}}
Add-LocalGroupMember -Group 'Remote Desktop Users' -Member {name} -ErrorAction SilentlyContinue
if ({admin}) {{ Add-LocalGroupMember -Group 'Administrators' -Member {name} -ErrorAction SilentlyContinue }}
Write-Output 'OK'
"""

_PS_DESTROY = r"""
$ErrorActionPreference='SilentlyContinue'
# 注销该账号所有活动会话
$q = quser 2>$null
if ($q) {{
  $q | Select-Object -Skip 1 | ForEach-Object {{
    $cols = ($_ -replace '^>','').Trim() -split '\s+'
    if ($cols[0] -ieq {name}) {{
      $sid = ($cols | Where-Object {{ $_ -match '^\d+$' }} | Select-Object -First 1)
      if ($sid) {{ logoff $sid }}
    }}
  }}
}}
Remove-LocalUser -Name {name} -ErrorAction SilentlyContinue
if ({delprofile}) {{
  Get-CimInstance Win32_UserProfile | Where-Object {{ $_.LocalPath -like ('*\' + {name}) }} | Remove-CimInstance -ErrorAction SilentlyContinue
}}
Write-Output 'OK'
"""
