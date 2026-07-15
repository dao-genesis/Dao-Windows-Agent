"""单账号多分身·**通用隔离层**（把三条隔离机制归一成一套底层决策·纯逻辑可离线单测）。

道法自然：此前各轮各自落地了三条**互不统属**的隔离机制——

    1. RDP 会话隔离（`desktop/tunnel` 租约：单账号 rdpwrap 多路会话，各自完整桌面栈）；
    2. CreateDesktop 隔离桌面（`core/adapter/win_desktop.py`：同会话内独立 HDESK + 消息级 I/O）；
    3. 应用层 user-data-dir 隔离（`core/clone/app_isolation.py`：收窄 Electron 单实例锁作用域）。

用户本源诉求（本轮重申）：**不要零散地"给某几个软件做隔离"，而要一个从底层打通一切的
通用层**——给定"要为某分身隔离运行某软件"，本层自动在三条机制里**选出能真正保证隔离的
最省成本档位**，并**如实报告**该档位对该软件的隔离保证（无物非彼，无物非是）。

核心模型：把隔离能力排成一条**由强到弱的档位阶梯**（`IsolationTier`），把每个软件对隔离的
**最低需求**（`IsolationNeed`）也落在这条阶梯上；解析器在"环境当前可用的档位集合"里，挑出
**≥ 软件需求 的最省档位**。选不出（软件需求高于一切可用档位）即 `isolated=False` 并说明缺口，
绝不假装能隔离——这正是对 `app_isolation` "诚实边界"的通用化、体系化。

四条档位（强→弱，对齐本仓既有成果，非新造机制）：

    ACCOUNT  独立 Windows 本地账号（New-LocalUser）。OS 级全隔离：文件系统 / HKCU /
             全局命名对象 / GPU 会话皆独立。对**一切**软件都成立，成本最高。
    SESSION  单账号多路 RDP 会话（rdpwrap + fSingleSessionPerUser=0）。独立完整桌面栈、
             独立输入队列、独立 GPU 合成。**这是"一个 Windows 账号也能造出类多账号相互
             分离效果"的本源突破**——对 GUI / GPU / 全局互斥体软件皆成立，成本中。
    DESKTOP  CreateDesktop 隔离桌面（HDESK）+ 消息级 I/O。零配置、不抢用户焦点；隔离
             窗口栈与输入焦点，但**不隔离 per-user 全局互斥体、不做 GPU 离屏合成**。
    APPDATA  per-clone user-data-dir / 配置目录。把"有数据目录开关"的单实例软件的锁
             作用域从 per-user 收窄到 per-clone；只在**同一桌面/会话内**即生效，零配置。

选型直觉：Electron 单实例软件（VS Code/Devin Desktop/Chrome/Edge）→ APPDATA 即够；把单实例
互斥体钉死在全局命名空间且无开关的软件、或必须真 GPU 合成的软件 → 必须 SESSION（或 ACCOUNT）；
天生多开的软件 → 无需任何隔离档位。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, Iterable, List, Optional

from core.clone.app_isolation import (
    ISOLATION_REGISTRY,
    CloneLaunchSpec,
    build_clone_launch,
    clone_data_root,
)


class IsolationTier(IntEnum):
    """隔离档位阶梯（数值越大隔离越强、成本通常越高）。"""

    NONE = 0      # 裸启动，无隔离
    APPDATA = 1   # per-clone user-data-dir（同桌面内收窄单实例锁）
    DESKTOP = 2   # CreateDesktop 隔离桌面 + 消息级 I/O（零配置，不隔离全局互斥体/GPU）
    SESSION = 3   # 单账号多路 RDP 会话（完整桌面栈/输入/GPU，突破多 RDP 限制）
    ACCOUNT = 4   # 独立 Windows 账号（OS 级全隔离）

    @property
    def label(self) -> str:
        return {
            IsolationTier.NONE: "none",
            IsolationTier.APPDATA: "appdata",
            IsolationTier.DESKTOP: "desktop",
            IsolationTier.SESSION: "session",
            IsolationTier.ACCOUNT: "account",
        }[self]


# 零配置即可用的档位（不需要建账号、不需要装 rdpwrap）。
ZERO_CONFIG_TIERS: frozenset[IsolationTier] = frozenset(
    {IsolationTier.NONE, IsolationTier.APPDATA, IsolationTier.DESKTOP}
)
# 全部档位（环境完全就绪：rdpwrap 已装 + 允许建账号）。
ALL_TIERS: frozenset[IsolationTier] = frozenset(IsolationTier)


class SingleInstanceKind(IntEnum):
    """软件的多开/单实例行为——决定它对隔离的**最低档位需求**。"""

    MULTI_INSTANCE = 0   # 天生可多开，互不干扰 → 无需隔离
    DATA_DIR_LOCK = 1    # 单实例锁在 user-data-dir 内 → APPDATA 即可
    GLOBAL_MUTEX = 2     # 单实例互斥体钉在全局命名空间且无开关 → 需 SESSION 及以上
    GPU_COMPOSITED = 3   # 必须真 GPU 合成（离屏桌面画不出）→ 需 SESSION 及以上
    PACKAGED_APP = 4     # UWP/打包应用：激活走 app broker，无视 lpDesktop，上不了 HDESK → 需 SESSION 及以上


# 各 kind 对应的**最低隔离档位需求**。
_MIN_TIER_FOR_KIND: Dict[SingleInstanceKind, IsolationTier] = {
    SingleInstanceKind.MULTI_INSTANCE: IsolationTier.NONE,
    SingleInstanceKind.DATA_DIR_LOCK: IsolationTier.APPDATA,
    SingleInstanceKind.GLOBAL_MUTEX: IsolationTier.SESSION,
    SingleInstanceKind.GPU_COMPOSITED: IsolationTier.SESSION,
    SingleInstanceKind.PACKAGED_APP: IsolationTier.SESSION,
}


@dataclass(frozen=True)
class AppIsolationNeed:
    """一个软件对隔离的需求画像。"""

    app_id: str
    kind: SingleInstanceKind
    note: str = ""

    @property
    def min_tier(self) -> IsolationTier:
        return _MIN_TIER_FOR_KIND[self.kind]


# 软件隔离需求登记表。凡在 app_isolation.ISOLATION_REGISTRY 里有 user-data-dir/env 策略的，
# 天然属 DATA_DIR_LOCK（APPDATA 即可隔离）；此处额外登记"需要更强档位"或"天生多开"的软件。
NEED_REGISTRY: Dict[str, AppIsolationNeed] = {
    # Electron/Chromium 家族：单实例锁在 user-data-dir 内 → APPDATA 即够。
    "vscode": AppIsolationNeed("vscode", SingleInstanceKind.DATA_DIR_LOCK,
                               "Electron 单实例锁在 user-data-dir 内"),
    "devin-desktop": AppIsolationNeed("devin-desktop", SingleInstanceKind.DATA_DIR_LOCK,
                                      "Devin Desktop = VS Code/Electron 内核"),
    "chrome": AppIsolationNeed("chrome", SingleInstanceKind.DATA_DIR_LOCK,
                               "Chromium 单实例锁在 user-data-dir 内"),
    "edge": AppIsolationNeed("edge", SingleInstanceKind.DATA_DIR_LOCK,
                             "Chromium 单实例锁在 user-data-dir 内"),
    # FreeCAD 默认允许多开，只需 env 隔离偏好即可，本质是天生多开 + 可选 APPDATA。
    "freecad": AppIsolationNeed("freecad", SingleInstanceKind.DATA_DIR_LOCK,
                                "默认可多开，隔离 FREECAD_USER_HOME 避免偏好互相覆盖"),
    # 全局互斥体、无数据目录开关的典型：Office/微信/钉钉这类 → 单账号内必须 SESSION 及以上。
    "office": AppIsolationNeed("office", SingleInstanceKind.GLOBAL_MUTEX,
                               "全局命名互斥体、无 user-data-dir 开关，同会话内无法多开"),
    "wechat": AppIsolationNeed("wechat", SingleInstanceKind.GLOBAL_MUTEX,
                               "全局互斥体单实例，需独立会话/账号才能多开"),
    # Win11 现代记事本是打包应用：System32\notepad.exe 只是激活存根，真进程经 app broker
    # 拉起、无视 STARTUPINFOW.lpDesktop，窗口永远不会落在 CreateDesktop 隔离桌面上
    # （真机 QEMU Win11 实测：pid 拉起但隔离桌面 enum_windows 永远为空）。
    "notepad": AppIsolationNeed("notepad", SingleInstanceKind.PACKAGED_APP,
                                "Win11 记事本=打包应用，激活无视 lpDesktop，HDESK 隔离桌面上不了；"
                                "需独立 RDP 会话/账号（Win10 经典记事本不受此限）"),
}


def _resolve_key(app_id: str) -> str:
    """归一到隔离策略键（复用 app_isolation 的别名，再叠加本层别名）。"""
    # 复用 build_clone_launch 的别名解析：其结果 app_id 即规范键。
    spec = build_clone_launch(app_id or "", "probe")
    return spec.app_id


def need_for(app_id: str) -> AppIsolationNeed:
    """查某软件的隔离需求画像。

    优先查 NEED_REGISTRY；未登记但在 app_isolation 有隔离策略者，按 DATA_DIR_LOCK 处理；
    完全未登记的软件**保守**按 GLOBAL_MUTEX 处理——即"假设它是恼人的单实例软件，需要
    最强的桌面级隔离才敢保证"，绝不乐观假设它能零配置隔离。
    """
    key = _resolve_key(app_id)
    if key in NEED_REGISTRY:
        return NEED_REGISTRY[key]
    if key in ISOLATION_REGISTRY:
        return AppIsolationNeed(key, SingleInstanceKind.DATA_DIR_LOCK,
                                ISOLATION_REGISTRY[key].note or "有 user-data-dir 隔离策略")
    return AppIsolationNeed(key, SingleInstanceKind.GLOBAL_MUTEX,
                            "未登记软件：保守假设为全局互斥体单实例，需会话级隔离才保证")


@dataclass(frozen=True)
class IsolationPlan:
    """通用隔离层对一次"为分身隔离运行某软件"请求的裁决。

    tier            实际选中的隔离档位。
    isolated        选中档位是否**满足**该软件的最低隔离需求（是否真能保证互不干扰）。
    min_tier        该软件所需的最低档位。
    placement       桌面落点：account / rdp-session / hdesk / shared（无独立桌面）。
    app_launch      APPDATA 层的启动规格（凡登记了 user-data-dir 策略即附带，作为叠加加固；
                    即便靠 SESSION 隔离，也顺带按分身派生数据目录，双保险且偏好互不覆盖）。
    reason          裁决与诚实边界说明。
    fallback_from   若首选（最省成本）档位不可用而降级/升级选中，记录被跳过的更省档位。
    """

    app_id: str
    clone_id: str
    tier: IsolationTier
    isolated: bool
    min_tier: IsolationTier
    placement: str
    app_launch: Optional[CloneLaunchSpec]
    reason: str
    fallback_from: List[str]

    def to_dict(self) -> dict:
        return {
            "app_id": self.app_id,
            "clone_id": self.clone_id,
            "tier": self.tier.label,
            "isolated": self.isolated,
            "min_tier": self.min_tier.label,
            "placement": self.placement,
            "app_launch": self.app_launch.to_dict() if self.app_launch else None,
            "reason": self.reason,
            "fallback_from": list(self.fallback_from),
        }


_PLACEMENT = {
    IsolationTier.ACCOUNT: "account",
    IsolationTier.SESSION: "rdp-session",
    IsolationTier.DESKTOP: "hdesk",
    IsolationTier.APPDATA: "shared",
    IsolationTier.NONE: "shared",
}


def _normalize_available(available: Optional[Iterable[IsolationTier]]) -> frozenset[IsolationTier]:
    if available is None:
        return frozenset(ZERO_CONFIG_TIERS)
    tiers = set(available)
    # NONE 永远可用（裸启动是兜底）。
    tiers.add(IsolationTier.NONE)
    return frozenset(tiers)


def resolve_isolation(
    app_id: str,
    clone_id: str,
    available_tiers: Optional[Iterable[IsolationTier]] = None,
    prefer_strongest: bool = False,
) -> IsolationPlan:
    """通用隔离层核心：为"分身 clone_id 隔离运行 app_id"选出隔离方案。

    available_tiers  当前环境**可用**的档位集合（如未装 rdpwrap 则不含 SESSION；不允许
                     建账号则不含 ACCOUNT）。缺省=零配置三档 {NONE, APPDATA, DESKTOP}。
    prefer_strongest 为 True 时在"满足需求的档位"里选最强者（追求最高隔离度）；缺省 False
                     选**满足需求的最省成本档位**（道法自然·够用即止）。

    返回 IsolationPlan：选中档位、是否真隔离、桌面落点、APPDATA 叠加规格、诚实说明。
    """
    avail = _normalize_available(available_tiers)
    need = need_for(app_id)
    min_tier = need.min_tier
    key = need.app_id

    # 候选：可用且 ≥ 最低需求 的档位。
    eligible = sorted(t for t in avail if t >= min_tier)

    # APPDATA 叠加规格：凡登记了 user-data-dir 策略即附带（哪怕靠更强档位隔离，也顺带派生
    # 分身数据目录，令偏好/扩展互不覆盖，是无害的双保险）。
    app_launch = None
    if key in ISOLATION_REGISTRY:
        app_launch = build_clone_launch(app_id, clone_id)

    if eligible:
        chosen = eligible[-1] if prefer_strongest else eligible[0]
        skipped = [t.label for t in sorted(avail) if t < chosen and t >= IsolationTier.APPDATA]
        reason = (
            f"{key} 最低需 {min_tier.label} 隔离；选中可用档位 {chosen.label}"
            f"（{'最强' if prefer_strongest else '最省成本'}）→ 真隔离成立。"
        )
        return IsolationPlan(
            app_id=key, clone_id=clone_id, tier=chosen, isolated=True,
            min_tier=min_tier, placement=_PLACEMENT[chosen], app_launch=app_launch,
            reason=reason, fallback_from=skipped,
        )

    # 没有任何可用档位满足需求 → 如实报告无法保证隔离，给出最接近的可用档位与缺口。
    best_avail = max(avail)
    reason = (
        f"{key} 最低需 {min_tier.label} 隔离，但当前可用档位最高仅 {best_avail.label}"
        f"（缺口：需在环境里启用 {min_tier.label} 档位，如装 rdpwrap 开多会话 或 建独立账号）"
        f"——如实告知：单靠现有档位无法保证 {key} 多分身互不干扰。"
    )
    return IsolationPlan(
        app_id=key, clone_id=clone_id, tier=best_avail, isolated=False,
        min_tier=min_tier, placement=_PLACEMENT[best_avail], app_launch=app_launch,
        reason=reason, fallback_from=[],
    )


def isolation_matrix(
    app_ids: Iterable[str],
    available_tiers: Optional[Iterable[IsolationTier]] = None,
    prefer_strongest: bool = False,
) -> Dict[str, dict]:
    """一次算出多软件的隔离方案矩阵（供诊断/文档/面板展示"哪些软件当前能真隔离"）。"""
    return {
        app_id: resolve_isolation(app_id, "probe", available_tiers, prefer_strongest).to_dict()
        for app_id in app_ids
    }


__all__ = [
    "IsolationTier",
    "SingleInstanceKind",
    "AppIsolationNeed",
    "IsolationPlan",
    "NEED_REGISTRY",
    "ZERO_CONFIG_TIERS",
    "ALL_TIERS",
    "need_for",
    "resolve_isolation",
    "isolation_matrix",
    "clone_data_root",
]
