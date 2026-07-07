"""内置画像注册：把各仓库现有软件驱动收编为统一 profile。"""
from __future__ import annotations

from core.profiles.builtin import freecad, jlceda, kicad, notepad
from core.profiles.registry import ProfileRegistry


def build_default_registry() -> ProfileRegistry:
    reg = ProfileRegistry()
    reg.register(kicad.PROFILE, lambda p: kicad._ADAPTER(p))
    reg.register(freecad.PROFILE, lambda p: freecad._ADAPTER(p))
    reg.register(jlceda.PROFILE, lambda p: jlceda._ADAPTER(p))
    reg.register(notepad.PROFILE, lambda p: notepad._ADAPTER(p))
    return reg
