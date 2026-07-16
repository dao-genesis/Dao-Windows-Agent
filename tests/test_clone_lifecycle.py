"""分身生命周期治理单测：心跳三态裁决 + 超时回收，注入时钟离线推进。"""
from __future__ import annotations

import pytest

from core.clone.lifecycle import CloneLifecycle


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def make() -> tuple[CloneLifecycle, FakeClock]:
    clk = FakeClock()
    return CloneLifecycle(clock=clk), clk


def test_register_and_alive():
    lc, _ = make()
    rec = lc.register("s2", "vscode", tier="desktop", ttl=60)
    assert rec.clone_id == "s2" and rec.app_id == "vscode"
    h = lc.health()
    assert h["total"] == 1 and h["counts"]["alive"] == 1
    assert h["clones"][0]["state"] == "alive" and h["clones"][0]["tier"] == "desktop"


def test_register_requires_ids():
    lc, _ = make()
    with pytest.raises(ValueError):
        lc.register("", "vscode")
    with pytest.raises(ValueError):
        lc.register("s1", "")


def test_heartbeat_keeps_alive_and_ghost_is_honest():
    lc, clk = make()
    lc.register("s1", "notepad", ttl=10)
    clk.t += 8
    assert lc.heartbeat("s1") is not None
    clk.t += 8  # 距上次心跳仅 8s < ttl
    assert lc.health()["clones"][0]["state"] == "alive"
    # 幽灵分身不凭空建档
    assert lc.heartbeat("ghost") is None


def test_three_states_and_gc():
    lc, clk = make()
    lc.register("s1", "notepad", ttl=10, grace=2.0)
    clk.t += 15  # ttl < 15 <= ttl*grace → stale
    assert lc.health()["clones"][0]["state"] == "stale"
    # stale 不被回收
    out = lc.gc()
    assert out["reclaimed"] == [] and out["remaining"] == 1
    clk.t += 10  # 距心跳 25 > 20 → expired
    assert lc.health()["clones"][0]["state"] == "expired"
    # 预演回收不摘除
    dry = lc.gc(dry_run=True)
    assert dry["reclaimed"] == ["s1"] and dry["remaining"] == 1
    # 真回收
    out = lc.gc()
    assert out["reclaimed"] == ["s1"] and out["remaining"] == 0
    assert lc.health()["total"] == 0


def test_drop_explicit():
    lc, _ = make()
    lc.register("s1", "notepad")
    assert lc.drop("s1") is True
    assert lc.drop("s1") is False


def test_register_idempotent_updates():
    lc, clk = make()
    lc.register("s1", "notepad", ttl=10)
    clk.t += 100
    rec = lc.register("s1", "notepad")  # 再登记即续心跳
    assert rec.beats == 2
    assert lc.health()["clones"][0]["state"] == "alive"
