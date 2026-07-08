"""内置画像注册：把各仓库现有软件驱动收编为统一 profile。"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.profiles.builtin import freecad, jlceda, kicad, mspaint, notepad, system
from core.profiles.registry import ProfileRegistry


def build_default_registry(uia_driver: Optional[Callable[[str, dict], Any]] = None,
                           vision_grounder: Optional[Callable[[str, dict], Any]] = None) -> ProfileRegistry:
    """构建内置画像注册表。

    级别② 的 uia_driver：未显式传入时，尝试自动探测 guest 内实机 driver（纯 ctypes 消息级，
    只需 Windows，无第三方依赖）；探测不到（如 Linux/CI）则为 None → 级别② 适配器进入
    dry-run，纯逻辑仍可单测。
    """
    if uia_driver is None:
        try:
            from core.adapter.uia_win import make_driver
            uia_driver = make_driver()
        except Exception:  # noqa: BLE001 - 探测失败即退回 dry-run
            uia_driver = None

    reg = ProfileRegistry()
    reg.register(system.PROFILE, lambda p: system._ADAPTER(p))
    reg.register(kicad.PROFILE, lambda p: kicad._ADAPTER(p))
    reg.register(freecad.PROFILE, lambda p: freecad._ADAPTER(p))
    reg.register(jlceda.PROFILE, lambda p: jlceda._ADAPTER(p))
    reg.register(notepad.PROFILE, lambda p: notepad._ADAPTER(p, driver=uia_driver))
    reg.register(mspaint.PROFILE, lambda p: mspaint._ADAPTER(p, grounder=vision_grounder))
    return reg
