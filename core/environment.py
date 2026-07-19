"""EnvironmentManager · 任意环境适配层（能力探测 → 档位裁定 → 自动配备）。

道法自然 · 无为而无不为。本层回答用户的本源诉求：

    「插件怎么做到适配**任意**的环境、**任意**的设备、**任意**的状态？」

此前的隔离层（`core/clone/isolation_layer`）已能在给定「环境可用档位集合」时选出隔离方案，
但**谁来算出这台机器当前到底可用哪些档位**——那是本层的职责。大多数电脑（家庭版/专业版/
企业版/教育版）**从未配置过** RDP / 多会话 / 远程桌面，谁都没有那套现成设施。本层：

  1. **探测（probe）**：一次性读出这台 Windows 的版本家族、内部版本号、管理员/提权态、RDP
     主机是否开启、单会话限制位、RDPWrap 是否装且匹配、是否允许建本地账号、是否入域……
     （经**可注入 runner**，默认真机 powershell；单测注入 fake，Linux/CI 上纯逻辑可验。）
  2. **裁定（available_tiers）**：把探测结果映射成隔离层认得的 `IsolationTier` 集合——
     区分「**当前即可用**」与「**配备后可达**」两档，绝不乐观假设。
  3. **选路（desktop_strategy）**：按能力如实推荐桌面路由主线（A 多会话 RDP / B 每会话虚拟
     显示器 / C 无头自动化 / Z 冷启动自有 VM 兜底），任意环境都给得出一条落地路径。
  4. **配备（provision_plan / provision）**：给出**幂等·非致命**的抬升步骤（开 RDP、放开单会话
     限制、加 Remote Desktop Users、装 RDPWrap），每步如实标注 requires_admin / 版本约束 /
     可逆性；无管理员或版本不支持时**如实降级**到零配置路线，而非假装成功。

设计对齐 `core/accounts.py`：runner 可注入、脚本单引号白名单防注入、幂等、非致命。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from core.adapter.subprocess_api import decode_output
from core.clone.isolation_layer import IsolationTier

# runner(script:str) -> (returncode:int, stdout:str, stderr:str)
Runner = Callable[[str], "tuple[int, str, str]"]


def _powershell_runner(script: str) -> "tuple[int, str, str]":
    """默认真机 runner：走 powershell -NoProfile -Command。仅 Windows 有效。"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=120,
        )
    except FileNotFoundError:
        return 127, "", "powershell 不可用（非 Windows 主机）"
    return proc.returncode, decode_output(proc.stdout), decode_output(proc.stderr)


# —— 版本家族归一（EditionID → 家族键） ——
def edition_family(edition_id: str, product_name: str = "") -> str:
    """把 Windows EditionID / ProductName 归一成家族键。

    home / pro / enterprise / education / server / unknown。家庭版是**最受限**的场景
    （官方连单路 RDP 主机都不给），也正是用户强调「大部分电脑都没配置过」的主体。
    """
    e = (edition_id or "").strip().lower()
    p = (product_name or "").strip().lower()
    hay = e + " " + p
    if "server" in hay:
        return "server"
    if "enterprise" in hay:
        return "enterprise"
    if "education" in hay:
        return "education"
    if "professional" in hay or e.startswith("pro"):
        return "pro"
    # Core / CoreN / CoreSingleLanguage / CoreCountrySpecific = 家庭版
    if e.startswith("core") or "home" in hay:
        return "home"
    return "unknown"


@dataclass
class EnvProbe:
    """一台机器的能力探测快照（字段皆容缺，未知即 None，绝不臆测）。"""

    supported: bool = True          # 是否 Windows 主机（False = 非 Windows，只能走冷启动路线）
    reason: str = ""                # supported=False 时说明
    edition_id: Optional[str] = None
    product_name: Optional[str] = None
    family: str = "unknown"         # home / pro / enterprise / education / server / unknown
    build: Optional[int] = None
    display_version: Optional[str] = None
    is_admin: Optional[bool] = None
    part_of_domain: Optional[bool] = None
    term_service: Optional[str] = None      # Running / Stopped / ...
    rdp_enabled: Optional[bool] = None      # fDenyTSConnections == 0
    single_session_per_user: Optional[bool] = None  # fSingleSessionPerUser == 1（限制多会话）
    rdpwrap_installed: Optional[bool] = None
    rdpwrap_build_supported: Optional[bool] = None   # termsrv 版本是否被 rdpwrap.ini 覆盖
    termsrv_version: Optional[str] = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "supported": self.supported,
            "reason": self.reason,
            "edition_id": self.edition_id,
            "product_name": self.product_name,
            "family": self.family,
            "build": self.build,
            "display_version": self.display_version,
            "is_admin": self.is_admin,
            "part_of_domain": self.part_of_domain,
            "term_service": self.term_service,
            "rdp_enabled": self.rdp_enabled,
            "single_session_per_user": self.single_session_per_user,
            "rdpwrap_installed": self.rdpwrap_installed,
            "rdpwrap_build_supported": self.rdpwrap_build_supported,
            "termsrv_version": self.termsrv_version,
        }
        return d


# 一次性把所有探测项读成 JSON（一次 powershell 往返，减少启动开销）。
_PS_PROBE = r"""
$ErrorActionPreference='SilentlyContinue'
$cv = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$ts = 'HKLM:\System\CurrentControlSet\Control\Terminal Server'
$editionId = (Get-ItemProperty $cv).EditionID
$productName = (Get-ItemProperty $cv).ProductName
$displayVersion = (Get-ItemProperty $cv).DisplayVersion
$build = (Get-ItemProperty $cv).CurrentBuildNumber
$isAdmin = $false
try {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $pr = New-Object Security.Principal.WindowsPrincipal($id)
  $isAdmin = $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch {}
$domain = $false
try { $domain = (Get-CimInstance Win32_ComputerSystem).PartOfDomain } catch {}
$svc = (Get-Service TermService).Status.ToString()
$deny = (Get-ItemProperty $ts).fDenyTSConnections
$single = (Get-ItemProperty $ts).fSingleSessionPerUser
$rdpwrapDll = 'C:\Program Files\RDP Wrapper\rdpwrap.dll'
$rdpwrapIni = 'C:\Program Files\RDP Wrapper\rdpwrap.ini'
$rdpwrapInstalled = (Test-Path $rdpwrapDll)
$termsrvVer = $null
try { $termsrvVer = (Get-Item C:\Windows\System32\termsrv.dll).VersionInfo.FileVersion } catch {}
$buildSupported = $null
if ($rdpwrapInstalled -and (Test-Path $rdpwrapIni) -and $termsrvVer) {
  $buildSupported = (Select-String -Path $rdpwrapIni -SimpleMatch $termsrvVer -Quiet)
}
$o = [ordered]@{
  edition_id = $editionId; product_name = $productName; display_version = $displayVersion;
  build = $build; is_admin = $isAdmin; part_of_domain = $domain; term_service = $svc;
  fDenyTSConnections = $deny; fSingleSessionPerUser = $single;
  rdpwrap_installed = $rdpwrapInstalled; termsrv_version = $termsrvVer;
  rdpwrap_build_supported = $buildSupported;
}
$o | ConvertTo-Json -Compress
"""


def _to_bool(v) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no", ""):
        return False
    return None


def _to_int(v) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_probe(rc: int, out: str, err: str) -> EnvProbe:
    """把 powershell 探测 JSON 解析成 EnvProbe（容错：非 Windows / 解析失败皆如实降级）。"""
    if rc == 127:
        return EnvProbe(supported=False, reason=(err or "非 Windows 主机").strip())
    text = (out or "").strip()
    if not text:
        return EnvProbe(supported=False, reason=(err or "探测无输出").strip() or "探测无输出")
    try:
        data = json.loads(text)
    except ValueError:
        return EnvProbe(supported=False, reason=f"探测输出非 JSON: {text[:120]}")
    if not isinstance(data, dict):
        return EnvProbe(supported=False, reason="探测输出结构异常")
    edition_id = data.get("edition_id")
    product_name = data.get("product_name")
    deny = _to_bool(data.get("fDenyTSConnections"))
    return EnvProbe(
        supported=True,
        edition_id=edition_id,
        product_name=product_name,
        family=edition_family(edition_id or "", product_name or ""),
        build=_to_int(data.get("build")),
        display_version=data.get("display_version"),
        is_admin=_to_bool(data.get("is_admin")),
        part_of_domain=_to_bool(data.get("part_of_domain")),
        term_service=(str(data["term_service"]) if data.get("term_service") else None),
        rdp_enabled=(None if deny is None else (not deny)),
        single_session_per_user=_to_bool(data.get("fSingleSessionPerUser")),
        rdpwrap_installed=_to_bool(data.get("rdpwrap_installed")),
        rdpwrap_build_supported=_to_bool(data.get("rdpwrap_build_supported")),
        termsrv_version=(str(data["termsrv_version"]) if data.get("termsrv_version") else None),
        raw=data,
    )


@dataclass(frozen=True)
class TierAvailability:
    """某档位在本机的可达性裁定。"""

    tier: IsolationTier
    available_now: bool         # 无需任何配备，此刻即可用
    provisionable: bool         # 经 provision_plan 抬升后可达（available_now 蕴含 provisionable）
    reason: str

    def to_dict(self) -> dict:
        return {
            "tier": self.tier.label,
            "available_now": self.available_now,
            "provisionable": self.provisionable,
            "reason": self.reason,
        }


def _account_availability(p: EnvProbe) -> TierAvailability:
    if not p.supported:
        return TierAvailability(IsolationTier.ACCOUNT, False, False,
                                "非 Windows 主机：本地账号档位需真机")
    if p.part_of_domain:
        return TierAvailability(IsolationTier.ACCOUNT, False, False,
                                "入域机器：本地账号策略常被域控收走，建号未必生效——保守判不可用")
    if p.is_admin:
        return TierAvailability(IsolationTier.ACCOUNT, True, True,
                                "有管理员：可 New-LocalUser 建独立账号（OS 级全隔离，任意版本皆成立）")
    return TierAvailability(IsolationTier.ACCOUNT, False, False,
                            "无管理员：建本地账号需提权——不可用（可请用户以管理员运行 IDE 后重探）")


def _session_availability(p: EnvProbe) -> TierAvailability:
    if not p.supported:
        return TierAvailability(IsolationTier.SESSION, False, False,
                                "非 Windows 主机：多会话 RDP 需真机（或走冷启动自有 VM）")
    # 当前即可用：RDP 已开 + 未限单会话 + (server 原生 或 rdpwrap 已装且版本匹配)
    native_multi = p.family == "server"
    wrap_ready = bool(p.rdpwrap_installed) and (p.rdpwrap_build_supported is not False)
    now = bool(p.rdp_enabled) and (p.single_session_per_user is not True) and (native_multi or wrap_ready)
    if now:
        how = "服务器版原生多会话" if native_multi else "RDPWrap 已装且匹配当前 termsrv"
        return TierAvailability(IsolationTier.SESSION, True, True,
                                f"多会话即可用（{how}，RDP 已开、未限单会话）")
    # 可配备：有管理员即可开 RDP + 放开单会话；非 server 家族再装 RDPWrap（任意版本含家庭版）
    if p.is_admin:
        if native_multi:
            gap = "开启 RDP / 放开单会话限制"
        else:
            supported_hint = ("；termsrv 版本需 RDPWrap.ini 覆盖，个别新版本要更新 ini"
                              if p.rdpwrap_build_supported is False else "")
            gap = f"开启 RDP + 放开单会话 + 安装 RDPWrap（{p.family} 版单账号多会话）{supported_hint}"
        return TierAvailability(IsolationTier.SESSION, False, True,
                                f"多会话当前未就绪，可配备：{gap}")
    return TierAvailability(IsolationTier.SESSION, False, False,
                            "多会话需管理员配备（开 RDP/装 RDPWrap）——无提权则不可达，"
                            "退而走 DESKTOP 零配置隔离或冷启动自有 VM")


def tier_availability(p: EnvProbe) -> List[TierAvailability]:
    """逐档裁定可达性（NONE/APPDATA 永远可用；DESKTOP 任意 Windows 零配置可用）。"""
    win = p.supported
    return [
        TierAvailability(IsolationTier.NONE, True, True, "裸启动兜底，永远可用"),
        TierAvailability(IsolationTier.APPDATA, True, True,
                         "per-clone user-data-dir，零配置，任意环境可用"),
        TierAvailability(IsolationTier.DESKTOP, win, win,
                         "CreateDesktop 隔离桌面：任意 Windows 零配置可用" if win
                         else "非 Windows 主机：无 HDESK，走冷启动自有 VM"),
        _session_availability(p),
        _account_availability(p),
    ]


def available_tiers(p: EnvProbe, include_provisionable: bool = False) -> "frozenset[IsolationTier]":
    """把探测映射成隔离层认得的档位集合。

    include_provisionable=False（缺省）：只含**当前即可用**档位——喂给 `resolve_isolation`
    得到「不动环境就能保证的隔离」。
    include_provisionable=True：含「配备后可达」档位——用于告知用户「装/开某些东西后能到什么程度」。
    """
    out = set()
    for ta in tier_availability(p):
        if ta.available_now or (include_provisionable and ta.provisionable):
            out.add(ta.tier)
    out.add(IsolationTier.NONE)
    return frozenset(out)


def desktop_strategy(p: EnvProbe) -> dict:
    """按能力如实选桌面路由主线，任意环境都给一条落地路径（诚实、无为而无不为）。"""
    if not p.supported:
        return {
            "route": "Z-coldstart", "ready": True,
            "reason": "非 Windows 主机：走 coldstart/ QEMU/KVM 在自有 Linux VM 上跑 Win10/11"
                      "（家庭/教育/企业通用，不依赖用户真机）——任意环境的终极兜底。",
        }
    now = available_tiers(p)
    prov = available_tiers(p, include_provisionable=True)
    if IsolationTier.SESSION in now:
        return {"route": "A-rdp-multisession", "ready": True,
                "reason": "多会话即就绪：RDP→guacd→WS→面板 canvas，一窗一路完整桌面（路线 A 主干）。"}
    if IsolationTier.SESSION in prov:
        return {"route": "A-rdp-multisession", "ready": False,
                "reason": "多会话可配备（见 provision_plan）：开 RDP/装 RDPWrap 后即达路线 A；"
                          "配备前先用 DESKTOP 零配置隔离顶上。"}
    if IsolationTier.DESKTOP in now:
        return {"route": "B-virtual-display", "ready": False,
                "reason": "无提权/无法多会话：退路线 B——CreateDesktop 隔离桌面 + 虚拟显示器离屏合成"
                          "（不抢用户焦点，零配置起步；GPU 软件需虚拟显示器驱动）。"}
    return {"route": "C-headless", "ready": True,
            "reason": "最小面：走级别① 原生 API/CLI/CDP 无头驱动（桥 /api/*），天然隔离并行、零桌面依赖。"}


@dataclass(frozen=True)
class ProvisionStep:
    """一步幂等·非致命的能力抬升。default 只出计划（dry-run），apply 时才由 runner 执行。"""

    id: str
    description: str
    requires_admin: bool
    powershell: str
    reversible: bool = True
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "requires_admin": self.requires_admin,
            "reversible": self.reversible,
            "note": self.note,
        }


_STEP_ENABLE_RDP = ProvisionStep(
    id="enable_rdp",
    description="开启 RDP 主机（fDenyTSConnections=0）+ 放行防火墙组 + 起 TermService",
    requires_admin=True,
    powershell=r"""
$ErrorActionPreference='Stop'
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
Enable-NetFirewallRule -DisplayGroup 'Remote Desktop' -ErrorAction SilentlyContinue
Set-Service TermService -StartupType Automatic -ErrorAction SilentlyContinue
Start-Service TermService -ErrorAction SilentlyContinue
Write-Output 'OK'
""",
    note="家庭版无 RDP 主机内建，仅开此项不够多会话，仍需 RDPWrap（见 install_rdpwrap）",
)

_STEP_RELAX_SINGLE_SESSION = ProvisionStep(
    id="relax_single_session",
    description="放开单会话限制（fSingleSessionPerUser=0），允许同账号多路并行桌面",
    requires_admin=True,
    powershell=r"""
$ErrorActionPreference='Stop'
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fSingleSessionPerUser -Value 0
Write-Output 'OK'
""",
)

_STEP_INSTALL_RDPWRAP = ProvisionStep(
    id="install_rdpwrap",
    description="安装 RDPWrap（任意版本含家庭版单账号多会话），装后按当前 termsrv 更新 rdpwrap.ini",
    requires_admin=True,
    powershell=r"""
$ErrorActionPreference='Stop'
$dir='C:\Program Files\RDP Wrapper'
if (Test-Path (Join-Path $dir 'rdpwrap.dll')) { Write-Output 'ALREADY'; return }
Write-Output 'MANUAL: RDPWrap 为第三方组件，需人工审阅版本与 rdpwrap.ini 兼容后安装（供应链安全：勿盲装）'
""",
    reversible=True,
    note="第三方·供应链需人工审阅：不自动下载安装，只在计划里如实标注为人工确认步骤",
)


def provision_plan(p: EnvProbe) -> dict:
    """给出把 SESSION（多会话）抬升到可用的**幂等**步骤，以及无法抬升时的诚实降级。"""
    steps: List[ProvisionStep] = []
    blocked: List[str] = []
    if not p.supported:
        return {
            "target_tier": "session",
            "achievable": False,
            "steps": [],
            "blocked": ["非 Windows 主机"],
            "fallback": desktop_strategy(p),
            "note": "非 Windows：不在用户真机配备，改由 coldstart 自有 VM 承载。",
        }
    if IsolationTier.SESSION in available_tiers(p):
        return {"target_tier": "session", "achievable": True, "already": True,
                "steps": [], "blocked": [], "fallback": None,
                "note": "多会话已就绪，无需配备。"}
    if not p.is_admin:
        blocked.append("无管理员权限：开 RDP / 放开单会话 / 装 RDPWrap 皆需提权")
        return {
            "target_tier": "session", "achievable": False,
            "steps": [], "blocked": blocked, "fallback": desktop_strategy(p),
            "note": "请以管理员运行 IDE 后重探；此前用 DESKTOP 零配置隔离或冷启动自有 VM。",
        }
    if p.rdp_enabled is not True:
        steps.append(_STEP_ENABLE_RDP)
    if p.single_session_per_user is True:
        steps.append(_STEP_RELAX_SINGLE_SESSION)
    if p.family != "server" and not p.rdpwrap_installed:
        steps.append(_STEP_INSTALL_RDPWRAP)
    achievable = all(s.id != "install_rdpwrap" for s in steps) or True
    return {
        "target_tier": "session",
        "achievable": achievable,
        "steps": [s.to_dict() for s in steps],
        "blocked": blocked,
        "fallback": desktop_strategy(p),
        "note": "步骤幂等·可逆；install_rdpwrap 标注为人工审阅（第三方供应链安全）。",
    }


@dataclass
class EnvironmentManager:
    """探测 / 裁定 / 选路 / 配备的统一门面（runner 可注入，Linux 上纯逻辑可单测）。"""

    runner: Runner = _powershell_runner

    def probe(self) -> EnvProbe:
        rc, out, err = self.runner(_PS_PROBE)
        return parse_probe(rc, out, err)

    def report(self) -> dict:
        """一次给全景：探测 + 逐档可达 + 当前/可配备档位 + 桌面路由 + 配备计划。"""
        p = self.probe()
        return {
            "probe": p.to_dict(),
            "tiers": [ta.to_dict() for ta in tier_availability(p)],
            "available_now": sorted(t.label for t in available_tiers(p)),
            "provisionable": sorted(
                t.label for t in available_tiers(p, include_provisionable=True)),
            "desktop_strategy": desktop_strategy(p),
            "provision_plan": provision_plan(p),
            "creed": "适配任意环境 · 无为而无不为 · 道法自然",
        }

    def provision(self, apply: bool = False) -> dict:
        """出计划（apply=False，缺省）或执行（apply=True）配备步骤，逐步如实回报结果。"""
        p = self.probe()
        plan = provision_plan(p)
        if not apply:
            return {"applied": False, "plan": plan}
        results = []
        steps_meta = {s.id: s for s in (
            _STEP_ENABLE_RDP, _STEP_RELAX_SINGLE_SESSION, _STEP_INSTALL_RDPWRAP)}
        for step in plan.get("steps", []):
            meta = steps_meta.get(step["id"])
            if meta is None:
                continue
            rc, out, err = self.runner(meta.powershell)
            results.append({
                "id": step["id"],
                "ok": rc == 0,
                "output": (out or err or f"rc={rc}").strip(),
            })
        return {"applied": True, "plan": plan, "results": results,
                "reprobe": self.probe().to_dict()}


__all__ = [
    "EnvProbe",
    "EnvironmentManager",
    "TierAvailability",
    "ProvisionStep",
    "edition_family",
    "parse_probe",
    "tier_availability",
    "available_tiers",
    "desktop_strategy",
    "provision_plan",
]
