"""分身生命周期治理（心跳 + 超时回收）· 纯逻辑可离线单测。

道法自然：`desktop/tunnel` 的**输入租约**有 TTL（久无续约即释放），但分身本体（clone）
本身却没有对称的存活治理——建了谁回收？崩了谁发现？这条不对称正是 Windows 体系报告
R9 认领的缺口。本模块补齐两个动词：

    clone_health   心跳 + 存活裁决：登记分身、续心跳、如实报告每个分身 alive/stale/expired。
    clone_gc       超时回收：把久无心跳（> ttl）的分身摘除，回报被回收者（对称于租约 TTL）。

与既有 `isolation_layer`（选隔离档位）互补：隔离层管"分身**怎么**隔离运行"，本层管
"分身**建了之后**的存活与回收"。二者都不触真机——纯登记/裁决逻辑，真机回收动作（杀进程、
销毁 HDESK、注销会话）由上层按本层裁决执行。

存活三态（对齐租约语义，诚实标注边界）：
    alive    最近一次心跳距今 ≤ ttl → 视为活。
    stale    ttl < 距今 ≤ ttl*grace → 疑似卡顿，尚未回收（给一个宽限窗口，避免误杀）。
    expired  距今 > ttl*grace → 判定已死，下次 gc 即回收。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# 默认心跳 TTL 与宽限系数（可 per-clone 覆盖）。
DEFAULT_TTL = 90.0        # 秒：超过即 stale
DEFAULT_GRACE = 2.0       # 宽限倍数：ttl*grace 后才判 expired


@dataclass
class CloneRecord:
    """一个分身的存活登记。"""

    clone_id: str
    app_id: str
    tier: str = ""                       # 隔离档位（isolation_layer 裁决结果，仅记录）
    ttl: float = DEFAULT_TTL
    grace: float = DEFAULT_GRACE
    created_at: float = 0.0
    last_beat: float = 0.0
    beats: int = 0
    meta: Dict[str, object] = field(default_factory=dict)

    def state(self, now: float) -> str:
        age = now - self.last_beat
        if age <= self.ttl:
            return "alive"
        if age <= self.ttl * self.grace:
            return "stale"
        return "expired"

    def to_dict(self, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        return {
            "clone_id": self.clone_id,
            "app_id": self.app_id,
            "tier": self.tier,
            "ttl": self.ttl,
            "grace": self.grace,
            "created_at": self.created_at,
            "last_beat": self.last_beat,
            "age": round(now - self.last_beat, 3),
            "beats": self.beats,
            "state": self.state(now),
            "meta": dict(self.meta),
        }


class CloneLifecycle:
    """分身存活登记与回收（对称于租约 TTL）。

    clock 可注入以离线断言时间推进（缺省 time.time）。所有操作纯内存——与
    SessionManager 同源的进程内生命周期态，HTTP 桥与 stdio MCP 经同一 BridgeService
    共享同一份登记，不各自割裂。
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._clones: Dict[str, CloneRecord] = {}

    def register(self, clone_id: str, app_id: str, *, tier: str = "",
                 ttl: Optional[float] = None, grace: Optional[float] = None,
                 meta: Optional[dict] = None) -> CloneRecord:
        """登记/幂等更新一个分身，并记一次心跳（创建即视为活）。"""
        if not clone_id:
            raise ValueError("clone_id 不能为空")
        if not app_id:
            raise ValueError("app_id 不能为空")
        now = self._clock()
        rec = self._clones.get(clone_id)
        if rec is None:
            rec = CloneRecord(clone_id=clone_id, app_id=app_id, created_at=now)
            self._clones[clone_id] = rec
        rec.app_id = app_id
        if tier:
            rec.tier = tier
        if ttl is not None:
            rec.ttl = float(ttl)
        if grace is not None:
            rec.grace = float(grace)
        if meta:
            rec.meta.update(meta)
        rec.last_beat = now
        rec.beats += 1
        return rec

    def heartbeat(self, clone_id: str) -> Optional[CloneRecord]:
        """续一次心跳；分身未登记则回 None（如实：不为幽灵分身凭空建档）。"""
        rec = self._clones.get(clone_id)
        if rec is None:
            return None
        rec.last_beat = self._clock()
        rec.beats += 1
        return rec

    def get(self, clone_id: str) -> Optional[CloneRecord]:
        return self._clones.get(clone_id)

    def drop(self, clone_id: str) -> bool:
        """显式摘除一个分身（正常销毁路径）。"""
        return self._clones.pop(clone_id, None) is not None

    def health(self) -> dict:
        """全体分身存活快照，并按三态汇总。"""
        now = self._clock()
        items = [rec.to_dict(now) for rec in self._clones.values()]
        items.sort(key=lambda d: (d["state"], d["clone_id"]))
        counts = {"alive": 0, "stale": 0, "expired": 0}
        for it in items:
            counts[it["state"]] += 1
        return {"now": now, "total": len(items), "counts": counts, "clones": items}

    def gc(self, dry_run: bool = False) -> dict:
        """回收已 expired 的分身（对称于租约 TTL 释放）。

        dry_run=True 只报告将被回收者、不实际摘除（供面板"预演回收"）。
        """
        now = self._clock()
        expired = [rec.to_dict(now) for rec in self._clones.values()
                   if rec.state(now) == "expired"]
        if not dry_run:
            for it in expired:
                self._clones.pop(it["clone_id"], None)
        return {
            "now": now,
            "dry_run": bool(dry_run),
            "reclaimed": [it["clone_id"] for it in expired],
            "detail": expired,
            "remaining": len(self._clones),
        }


__all__ = ["CloneRecord", "CloneLifecycle", "DEFAULT_TTL", "DEFAULT_GRACE"]
