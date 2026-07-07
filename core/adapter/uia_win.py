"""级别② 的 Windows 实机 driver：把 UiaDesktopAdapter 的动作计划落到真窗口。

**本源之路（道法自然）**：级别② 的执行走 **纯 ctypes 消息级**（Win32 window messages），
不依赖 pywinauto/pywin32/comtypes 任何第三方——因此**零配置、去中心化**，也彻底绕开
pywin32 的 DLL 注册地狱。只要是 Windows guest，`available()` 即为真。

为什么是消息级而非 UIA 坐标：
  · **隔离桌面不是"输入桌面"**——它不接管鼠标键盘焦点，故 SendInput/坐标点击/UIA 的
    `Desktop(backend='uia')` 枚举都够不着隔离桌面上的窗口（实测 UIA descendants 返回 0）。
  · 而 **窗口消息（WM_SETTEXT/WM_GETTEXT/WM_CHAR/BM_CLICK）按 hwnd 直达目标窗口**，
    与它在哪张桌面、是否为输入桌面无关，且**不抢用户焦点**——这正是"类多 RDP 隔离"的真身。
  · 实测：UIA `ElementFromHandle` 虽能按 hwnd 附着隔离桌面窗口，但其后代遍历在隔离桌面上
    不可靠；消息级 WM_SETTEXT→WM_GETTEXT 在 Win11 现代记事本(RichEditD2DPT)上稳定往返。

隔离桌面（本源修正）：每 (session, app) 一张 Win32 桌面(CreateDesktop)，由 `win_desktop`
纯 ctypes 基石落地——
  · 进程用 `CreateProcessW + STARTUPINFOW.lpDesktop` 真正起到隔离桌面
    （老路的 `subprocess.STARTUPINFO.lpDesktop` 是无效字段，进程会落到用户可见桌面）；
  · 执行线程用 `SetThreadDesktop` 绑到该桌面，窗口枚举/取图只作用于该桌面。
=> 与用户主桌面互不干扰、N 会话并行，达到"类多 RDP 会话隔离"而无需 RDP/建账号/RDPWrap。

非 Windows 平台 `available()` 返回 False，`build_default_registry` 退回 dry-run
（core 全程 import 无副作用、不依赖任何第三方，符合纯 stdlib 底座约定）。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from core.adapter import win_desktop

# 现代/经典编辑区类名（消息级 WM_SETTEXT/WM_GETTEXT 通吃）。
_EDIT_CLASSES = win_desktop._EDIT_CLASSES if hasattr(win_desktop, "_EDIT_CLASSES") else (
    "RichEditD2DPT", "Edit", "RichEdit20W", "RichEdit50W", "RICHEDIT60W", "NotepadTextBox",
)


def _quote(arg: str) -> str:
    """按 Windows 命令行规则给含空格的参数加引号（供 CreateProcessW 命令行拼装）。"""
    return f'"{arg}"' if (" " in arg and not arg.startswith('"')) else arg


def available() -> bool:
    """当前环境能否真正执行级别②：仅需 Windows + 隔离桌面能力（纯 ctypes，无第三方依赖）。"""
    return win_desktop.available()


class _WinMsgDriver:
    """消息级实机 driver（driver 契约：__call__(desktop, plan)）。

    每次 __call__ 用 `win_desktop.attached(desktop)` 把执行线程绑到该隔离桌面，全程窗口
    枚举/取图都只作用于此桌面 → 天然隔离、不抢用户焦点。窗口操作走 hwnd 消息级直达。
    """

    def __init__(self) -> None:
        self._pid: Optional[int] = None
        self._top: Optional[int] = None   # 当前顶层窗口 hwnd
        self._edit: Optional[int] = None  # 当前编辑控件 hwnd

    def __call__(self, desktop: str, plan: dict) -> dict:
        results: list[Any] = []
        self._top = None
        self._edit = None
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
            return self._find(desktop, step)
        if op == "set_value":
            return self._set_value(step)
        if op == "get_text":
            return self._get_text(step)
        if op in ("click", "invoke"):
            hwnd = self._resolve(step.get("target", {}))
            if not hwnd:
                return {"clicked": False, "reason": "target 未定位"}
            win_desktop.post_click(hwnd)
            return {"clicked": True}
        if op == "keys":
            return self._keys(step)
        if op == "menu":
            # 菜单路径依赖 UIA/焦点，隔离桌面上不可靠；本源路以消息级/快捷键替代
            return {"menu": step.get("path"), "note": "消息级不驱动菜单；请用 keys 快捷键或直接文件落盘"}
        if op == "tree":
            return self._tree(step)
        if op == "screenshot":
            return self._screenshot(desktop, step)
        return {"skipped_op": op}

    def _launch(self, desktop: str, step: dict) -> dict:
        # CreateProcessW + STARTUPINFOW.lpDesktop 真正把进程起到隔离桌面。
        parts = [_quote(step["exe"]), *[_quote(a) for a in step.get("args", [])]]
        cmdline = " ".join(parts)
        self._pid = win_desktop.launch_on_desktop(desktop, cmdline)
        # 等窗口出现（起进程后窗口异步创建）
        self._top = self._await_top(desktop, deadline=time.time() + 8)
        return {"pid": self._pid, "desktop": desktop, "hwnd": self._top}

    def _await_top(self, desktop: str, deadline: float) -> Optional[int]:
        while time.time() < deadline:
            wins = win_desktop.enum_windows(desktop)
            # 取带标题的最新顶层窗口（排除无标题的系统弹层）
            titled = [h for h, t in wins if t]
            if titled:
                return titled[-1]
            time.sleep(0.3)
        return None

    def _find(self, desktop: str, step: dict) -> dict:
        by, value = step.get("by"), step.get("value")
        deadline = time.time() + float(step.get("timeout", 8))
        while time.time() < deadline:
            # 顶层窗口刷新（对话框/新窗口可能刚出现）
            if self._top is None:
                self._top = self._await_top(desktop, deadline=time.time() + 0.5)
            if by == "control_type" and value in ("Edit", "Document", "Text"):
                if self._top:
                    self._edit = win_desktop.find_edit_control(self._top)
                    if self._edit:
                        return {"found": True, "hwnd": self._edit, "kind": "edit"}
            elif by == "name" and value:
                # 名称匹配：先在顶层窗口标题里找（如另存为对话框），再取其编辑控件
                hwnd = win_desktop.find_top_window(desktop, title_contains=value)
                if hwnd:
                    self._top = hwnd
                    self._edit = win_desktop.find_edit_control(hwnd)
                    return {"found": True, "hwnd": hwnd, "kind": "window"}
                # 再在当前窗口后代里按控件文本匹配
                if self._top:
                    for h, _cls, txt in win_desktop.list_children(self._top):
                        if value in txt:
                            self._edit = h
                            return {"found": True, "hwnd": h, "kind": "control"}
            else:
                # 兜底：只要拿到顶层窗口即视为定位成功
                if self._top:
                    return {"found": True, "hwnd": self._top, "kind": "window"}
            time.sleep(0.3)
        return {"found": False}

    def _resolve(self, target: dict) -> Optional[int]:
        """把 target 规格解析成一个具体 hwnd（编辑区/当前窗口）。"""
        by, value = target.get("by"), target.get("value")
        if by == "control_type" and value in ("Edit", "Document", "Text"):
            if self._edit is None and self._top:
                self._edit = win_desktop.find_edit_control(self._top)
            return self._edit
        return self._edit or self._top

    def _set_value(self, step: dict) -> dict:
        hwnd = self._resolve(step.get("target", {}))
        if not hwnd:
            return {"set": False, "reason": "编辑控件未定位"}
        text = step.get("text", "")
        win_desktop.set_text(hwnd, text)
        return {"set": True, "hwnd": hwnd}

    def _get_text(self, step: dict) -> dict:
        hwnd = self._resolve(step.get("target", {}))
        if not hwnd:
            return {"text": "", "reason": "编辑控件未定位"}
        return {"text": win_desktop.get_text(hwnd), "hwnd": hwnd}

    def _keys(self, step: dict) -> dict:
        # 消息级键：纯文本走 WM_CHAR 送入当前编辑控件；组合键/功能键需焦点，隔离桌面上不保证。
        keys = step.get("keys", "")
        hwnd = self._edit or self._top
        if hwnd and keys and not keys.startswith(("^", "%", "+", "{")):
            win_desktop.send_chars(hwnd, keys)
            return {"keys": keys, "sent": "wm_char"}
        return {"keys": keys, "note": "组合/功能键依赖输入焦点，隔离桌面上不经此路；文本请用 set_value"}

    def _tree(self, step: dict) -> dict:
        if not self._top:
            return {"tree": [], "reason": "无顶层窗口"}
        kids = win_desktop.list_children(self._top)
        return {"tree": [{"hwnd": h, "class": c, "text": t} for h, c, t in kids]}

    def _screenshot(self, desktop: str, step: dict) -> dict:
        if not self._top:
            self._top = self._await_top(desktop, deadline=time.time() + 3)
        if not self._top:
            return {"screenshot": None, "reason": "无顶层窗口"}
        path = f"C:\\dao_win\\shot_{int(time.time())}.bmp"
        try:
            win_desktop.capture_window(self._top, path)
            return {"screenshot": path, "hwnd": self._top}
        except Exception as exc:  # noqa: BLE001
            return {"screenshot": None, "error": f"{type(exc).__name__}: {exc}"}


def make_driver():
    """构造实机 driver；不可用时返回 None（调用方退回 dry-run）。"""
    if not available():
        return None
    try:
        return _WinMsgDriver()
    except Exception:  # noqa: BLE001
        return None
