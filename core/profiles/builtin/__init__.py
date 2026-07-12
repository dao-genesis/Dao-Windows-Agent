"""内置画像注册：把各仓库现有软件驱动收编为统一 profile。"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.profiles.builtin import browser, freecad, jlceda, kicad, mspaint, notepad, system
from core.profiles.registry import ProfileRegistry


def build_default_registry(uia_driver: Optional[Callable[[str, dict], Any]] = None,
                           vision_grounder: Optional[Callable[[str, dict], Any]] = None,
                           discover_subplugins: bool = False,
                           bind_osctl: bool = False,
                           autodetect_uia: bool = True,
                           browser_factory: Optional[Callable[[], Any]] = None,
                           cdp_evaluator: Optional[Callable[[str], Any]] = None) -> ProfileRegistry:
    """构建内置画像注册表。

    级别② 的 uia_driver：未显式传入时，尝试自动探测 guest 内实机 driver（纯 ctypes 消息级，
    只需 Windows，无第三方依赖）；探测不到（如 Linux/CI）则为 None → 级别② 适配器进入
    dry-run，纯逻辑仍可单测。`autodetect_uia=False` 可强制不探测（任意平台都走 dry-run）。
    """
    if bind_osctl and vision_grounder is None:
        # vendored agentctl 底座只供级别③ 像素/坐标兜底 grounder（mspaint 等在用户可见桌面
        # 的软件）。**不**拿它做级别② 的 uia_driver：agentctl 的 uia_find 依赖 UIA 树，而
        # 隔离桌面(CreateDesktop) 非输入桌面——UIA descendants 在其上恒为 0（实测 rect=None）。
        # 仅在 guest(Windows)/带 X 的 Linux 可加载；无对应后端即静默退回。
        try:
            from core.adapter.osctl_driver import load_osctl, make_grounder
            vision_grounder = make_grounder(load_osctl())
        except Exception:  # noqa: BLE001 - 底座不可用即退回
            pass

    if uia_driver is None and autodetect_uia:
        # 级别② 隔离桌面驱动**恒为消息级**（纯 ctypes WM_SETTEXT/WM_GETTEXT，按 hwnd 直达、
        # 跨桌面有效、不抢用户焦点）——这是隔离桌面上唯一可靠的控件级通道。
        try:
            from core.adapter.uia_win import make_driver
            uia_driver = make_driver()
        except Exception:  # noqa: BLE001 - 探测失败即退回 dry-run
            uia_driver = None

    reg = ProfileRegistry()
    reg.register(system.PROFILE, lambda p: system._ADAPTER(p))
    reg.register(browser.PROFILE,
                 lambda p: browser._ADAPTER(p, browser_factory=browser_factory))
    reg.register(kicad.PROFILE, lambda p: kicad._ADAPTER(p))
    reg.register(freecad.PROFILE, lambda p: freecad._ADAPTER(p))
    reg.register(jlceda.PROFILE, lambda p: jlceda._ADAPTER(p, evaluator=cdp_evaluator))
    reg.register(notepad.PROFILE, lambda p: notepad._ADAPTER(p, driver=uia_driver))
    reg.register(mspaint.PROFILE, lambda p: mspaint._ADAPTER(p, grounder=vision_grounder))
    if discover_subplugins:
        # 扫描发现目录，把已安装的领域子插件（外部 VS Code 扩展）自动收编为 @ 工作层。
        from core.subplugin import register_subplugins
        register_subplugins(reg)
    return reg
