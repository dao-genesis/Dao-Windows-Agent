"""级别② 的 Windows 实机 driver：把 UiaDesktopAdapter 的动作计划落到真 UIAutomation。

本模块**只在 Windows guest 内、且装了 pywinauto 时**才能真正执行；在 Linux/无依赖环境
`available()` 返回 False，`build_default_registry` 便退回 dry-run（core 全程 import 无副作用、
不依赖任何第三方，符合纯 stdlib 底座约定）。

隔离桌面（本源修正）：每 (session, app) 一张 Win32 桌面(CreateDesktop)，由 `win_desktop`
纯 ctypes 基石落地——
  · 进程用 `CreateProcessW + STARTUPINFOW.lpDesktop` 真正起到隔离桌面
    （老路的 `subprocess.STARTUPINFO.lpDesktop` 是无效字段，进程会落到用户可见桌面）；
  · 执行线程用 `SetThreadDesktop` 绑到该桌面，pywinauto 的 Desktop(backend='uia') 方能
    枚举到隔离桌面上的窗口（否则只看得到默认桌面，起在隔离桌面的窗口根本找不到）。
=> 与用户主桌面互不干扰、N 会话并行，达到"类多 RDP 会话隔离"而无需 RDP/建账号/RDPWrap。
coldstart/firstlogon.ps1 负责 `pip install --no-user pywinauto` 并把本 driver 绑进 guest 内的桥。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from core.adapter import win_desktop


def _quote(arg: str) -> str:
    """按 Windows 命令行规则给含空格的参数加引号（供 CreateProcessW 命令行拼装）。"""
    return f'"{arg}"' if (" " in arg and not arg.startswith('"')) else arg


def available() -> bool:
    """当前环境能否真正执行 UIA（Windows + 隔离桌面能力 + pywinauto）。"""
    if not win_desktop.available():
        return False
    try:
        import pywinauto  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


class _WinUiaDriver:
    """执行 UiaDesktopAdapter.build_plan 产出的动作计划（driver 契约：__call__(desktop, plan)）。

    每次 __call__ 用 `win_desktop.attached(desktop)` 把执行线程绑到该隔离桌面，全程 UIA
    枚举/操作都只作用于此桌面 → 天然隔离、不抢用户焦点。
    """

    def __init__(self) -> None:
        from pywinauto import Desktop  # 延迟导入：仅 guest 内可用

        self._Desktop = Desktop
        self._pid: Optional[int] = None
        self._win = None

    def __call__(self, desktop: str, plan: dict) -> dict:
        results: list[Any] = []
        self._win = None
        # 绑线程到隔离桌面：其内枚举/驱动只见该桌面窗口，退出自动还原
        with win_desktop.attached(desktop):
            for step in plan.get("steps", []):
                results.append(self._run_step(desktop, step))
        return {"verb": plan.get("verb"), "desktop": desktop, "results": results}

    # --- 单步执行 ---
    def _run_step(self, desktop: str, step: dict) -> Any:
        op = step.get("op")
        if op == "launch":
            return self._launch(desktop, step)
        if op == "find":
            self._win = self._find_window(step)
            return {"found": bool(self._win)}
        if op == "set_value":
            ctrl = self._locate(step.get("target", {}))
            ctrl.set_edit_text(step["text"]) if hasattr(ctrl, "set_edit_text") else ctrl.type_keys(step["text"], with_spaces=True)
            return {"set": True}
        if op == "get_text":
            ctrl = self._locate(step.get("target", {}))
            return {"text": ctrl.window_text() or (ctrl.get_value() if hasattr(ctrl, "get_value") else "")}
        if op in ("click", "invoke"):
            ctrl = self._locate(step.get("target", {}))
            ctrl.invoke() if (op == "invoke" and hasattr(ctrl, "invoke")) else ctrl.click_input()
            return {"clicked": True}
        if op == "keys":
            (self._win or self._top()).type_keys(step["keys"], set_foreground=True)
            return {"keys": step["keys"]}
        if op == "menu":
            self._top().menu_select(" -> ".join(step.get("path", [])))
            return {"menu": step.get("path")}
        if op == "tree":
            return {"tree": self._top().dump_tree(depth=int(step.get("depth", 3))) or "dumped"}
        if op == "screenshot":
            img = self._top().capture_as_image()
            path = f"C:\\dao_win\\shot_{int(time.time())}.png"
            img.save(path)
            return {"screenshot": path}
        return {"skipped_op": op}

    def _launch(self, desktop: str, step: dict) -> dict:
        # 用 win_desktop.launch_on_desktop（CreateProcessW + STARTUPINFOW.lpDesktop）
        # 真正把进程起到隔离桌面；老路的 subprocess.STARTUPINFO 无 lpDesktop 字段，进程会
        # 落到用户可见的默认桌面，隔离失效。
        parts = [_quote(step["exe"]), *[_quote(a) for a in step.get("args", [])]]
        cmdline = " ".join(parts)
        self._pid = win_desktop.launch_on_desktop(desktop, cmdline)
        time.sleep(1.0)
        return {"pid": self._pid, "desktop": desktop}

    def _find_window(self, step: dict, retry: int = 0):
        deadline = time.time() + float(step.get("timeout", 8))
        crit = self._criteria(step)
        while time.time() < deadline:
            try:
                w = self._Desktop(backend="uia").window(**crit)
                if w.exists():
                    return w
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
        return None

    def _locate(self, target: dict):
        base = self._win or self._top()
        crit = self._criteria(target)
        return base.child_window(**crit) if crit else base

    @staticmethod
    def _criteria(spec: dict) -> dict:
        by, value = spec.get("by"), spec.get("value")
        mapping = {"name": "title", "automation_id": "auto_id", "control_type": "control_type"}
        return {mapping[by]: value} if by in mapping and value is not None else {}

    def _top(self):
        return self._win or self._Desktop(backend="uia").windows()[0]


def make_driver():
    """构造实机 driver；不可用时返回 None（调用方退回 dry-run）。"""
    if not available():
        return None
    try:
        return _WinUiaDriver()
    except Exception:  # noqa: BLE001
        return None
