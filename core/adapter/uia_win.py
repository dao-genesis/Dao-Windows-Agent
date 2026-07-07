"""级别② 的 Windows 实机 driver：把 UiaDesktopAdapter 的动作计划落到真 UIAutomation。

本模块**只在 Windows guest 内、且装了 pywinauto 时**才能真正执行；在 Linux/无依赖环境
`available()` 返回 False，`build_default_registry` 便退回 dry-run（core 全程 import 无副作用、
不依赖任何第三方，符合纯 stdlib 底座约定）。

隔离桌面：每 (session, app) 一张 Win32 桌面(CreateDesktop)。pywinauto 的 Desktop(backend='uia')
在当前进程桌面内枚举控件；进程经 STARTUPINFO.lpDesktop 起在目标桌面 → 与用户主桌面互不干扰。
coldstart/firstlogon.ps1 负责 `pip install pywinauto` 并把本 driver 绑进 guest 内的 bridge。
"""
from __future__ import annotations

import subprocess
import time
from typing import Any, Optional


def available() -> bool:
    """当前环境能否真正执行 UIA（Windows + pywinauto）。"""
    try:
        import pywinauto  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


class _WinUiaDriver:
    """执行 UiaDesktopAdapter.build_plan 产出的动作计划（driver 契约：__call__(desktop, plan)）。"""

    def __init__(self) -> None:
        from pywinauto import Desktop  # 延迟导入：仅 guest 内可用

        self._Desktop = Desktop
        self._proc: Optional[subprocess.Popen] = None
        self._win = None

    def __call__(self, desktop: str, plan: dict) -> dict:
        results: list[Any] = []
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
        args = [step["exe"], *step.get("args", [])]
        si = subprocess.STARTUPINFO()
        si.lpDesktop = desktop  # 起在隔离桌面
        self._proc = subprocess.Popen(args, startupinfo=si)
        time.sleep(1.0)
        return {"pid": self._proc.pid, "desktop": desktop}

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
