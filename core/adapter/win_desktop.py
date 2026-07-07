"""级别② 的本源基石：单账号内**真·隔离桌面**（Win32 CreateDesktop）+ 无焦点抢占输入。

这是"把整台 Windows 做进 IDE、开 N 个窗口 = N 个互不干扰实例"的技术真身——
不走 RDP、不建账号、不装 RDPWrap，仅用 Windows 自带的 **桌面对象(HDESK)** 达到
"类多 RDP 会话隔离"的效果：每个 (session, app) 一张独立桌面，软件启动其上，
**不出现在用户可见的默认桌面**，输入用**消息级** PostMessage（不抢用户焦点）。

为什么必须有本模块（修正老路的两个致命 bug）：
1. Python 的 `subprocess.STARTUPINFO` **根本不暴露 `lpDesktop` 字段** —— 老 driver 里
   `si.lpDesktop = desk` 是无效赋值，进程照样落在**用户可见的默认桌面**，隔离完全落空。
   要把进程起到指定桌面，只能用 `CreateProcessW` + `STARTUPINFOW.lpDesktop`（本模块做）。
2. 驱动线程若不 `SetThreadDesktop(hdesk)` 绑到目标桌面，任何窗口枚举/UIA 都只看得到
   默认桌面 —— 起在隔离桌面上的窗口根本枚举不到。本模块提供 `attached()` 上下文管理器。

纯 ctypes、零第三方依赖；非 Windows 平台 `available()==False`，import 无副作用（守约：
core 全程 stdlib 底座、Linux/CI 可 import 与 dry-run）。真正执行只发生在 Windows guest 内。
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple

_IS_WIN = sys.platform == "win32"

# --- Win32 常量 ---
GENERIC_ALL = 0x10000000
DESKTOP_CREATEWINDOW = 0x0002
DESKTOP_ENUMERATE = 0x0040
DESKTOP_READOBJECTS = 0x0001
DESKTOP_WRITEOBJECTS = 0x0080
DESKTOP_SWITCHDESKTOP = 0x0100
DESKTOP_CREATEMENU = 0x0004
DESKTOP_HOOKCONTROL = 0x0008
DESKTOP_JOURNALRECORD = 0x0010
DESKTOP_JOURNALPLAYBACK = 0x0020
# 打开/新建桌面所需的合成访问位（足以起进程 + 枚举 + 输入）
DESKTOP_ALL = (
    DESKTOP_CREATEWINDOW | DESKTOP_ENUMERATE | DESKTOP_READOBJECTS
    | DESKTOP_WRITEOBJECTS | DESKTOP_SWITCHDESKTOP | DESKTOP_CREATEMENU
    | DESKTOP_HOOKCONTROL | DESKTOP_JOURNALRECORD | DESKTOP_JOURNALPLAYBACK
)

STARTF_USESHOWWINDOW = 0x00000001
SW_SHOWNORMAL = 1
NORMAL_PRIORITY_CLASS = 0x00000020

# 窗口消息（消息级输入，不抢焦点）
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
BM_CLICK = 0x00F5
WM_CLOSE = 0x0010


def available() -> bool:
    """当前平台能否真正创建/驱动隔离桌面（仅 Windows）。"""
    return _IS_WIN


def sanitize_name(name: str) -> str:
    """桌面名不得含反斜杠等分隔符；规整为合法对象名（Windows 桌面名 <= 一定长度）。"""
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)
    return safe[:96] or "dao_desktop"


if _IS_WIN:  # pragma: no cover - 仅 Windows guest 内执行
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    _user32.CreateDesktopW.restype = wintypes.HANDLE
    _user32.CreateDesktopW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    ]
    _user32.OpenDesktopW.restype = wintypes.HANDLE
    _user32.OpenDesktopW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    _user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    _user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
    _user32.SetThreadDesktop.restype = wintypes.BOOL
    _user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    _user32.GetThreadDesktop.restype = wintypes.HANDLE
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, _WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumDesktopWindows.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.SendMessageW.restype = wintypes.LPARAM
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL

    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION),
    ]
    _kernel32.CreateProcessW.restype = wintypes.BOOL

    def ensure_desktop(name: str) -> int:
        """打开同名桌面；不存在则创建。返回 HDESK（int）。失败抛 OSError。"""
        name = sanitize_name(name)
        h = _user32.OpenDesktopW(name, 0, False, DESKTOP_ALL)
        if not h:
            h = _user32.CreateDesktopW(name, None, None, 0, DESKTOP_ALL, None)
        if not h:
            raise ctypes.WinError(ctypes.get_last_error())
        return h

    def close_desktop(hdesk: int) -> None:
        if hdesk:
            _user32.CloseDesktop(hdesk)

    @contextmanager
    def attached(name: str) -> Iterator[int]:
        """把**当前线程**绑到隔离桌面：其内所有窗口枚举/UIA 只在该桌面生效；退出还原。

        用法：
            with attached(desk):
                # 此处枚举/驱动的都是隔离桌面上的窗口
        注意 SetThreadDesktop 要求调用线程当前没有任何窗口/hook。桥的执行线程应是干净的
        工作线程（server 已按会话在独立线程内执行 plan）。
        """
        hdesk = ensure_desktop(name)
        prev = _user32.GetThreadDesktop(_kernel32.GetCurrentThreadId())
        if not _user32.SetThreadDesktop(hdesk):
            close_desktop(hdesk)
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield hdesk
        finally:
            if prev:
                _user32.SetThreadDesktop(prev)
            close_desktop(hdesk)

    def launch_on_desktop(name: str, cmdline: str, workdir: Optional[str] = None) -> int:
        """用 CreateProcessW 把进程真正起到隔离桌面（STARTUPINFOW.lpDesktop）。返回 pid。

        cmdline 传完整命令行（可含参数），如 'notepad.exe C:\\a.txt'。
        """
        name = sanitize_name(name)
        ensure_desktop(name)  # 保证桌面存在
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(STARTUPINFOW)
        si.lpDesktop = name  # ← 关键：老路用 subprocess 无法设此字段，进程遂落默认桌面
        si.dwFlags = STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOWNORMAL
        pi = PROCESS_INFORMATION()
        buf = ctypes.create_unicode_buffer(cmdline)  # 可写缓冲（CreateProcessW 要求）
        ok = _kernel32.CreateProcessW(
            None, buf, None, None, False, NORMAL_PRIORITY_CLASS, None, workdir,
            ctypes.byref(si), ctypes.byref(pi),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        _kernel32.CloseHandle = getattr(_kernel32, "CloseHandle", None)
        if _kernel32.CloseHandle:
            _kernel32.CloseHandle(pi.hThread)
            _kernel32.CloseHandle(pi.hProcess)
        return int(pi.dwProcessId)

    def enum_windows(name: str, visible_only: bool = True) -> List[Tuple[int, str]]:
        """枚举隔离桌面上的顶层窗口，返回 [(hwnd, title), ...]。"""
        name = sanitize_name(name)
        hdesk = _user32.OpenDesktopW(name, 0, False, DESKTOP_ENUMERATE | DESKTOP_READOBJECTS)
        if not hdesk:
            return []
        out: List[Tuple[int, str]] = []

        def _cb(hwnd, _lparam):
            if visible_only and not _user32.IsWindowVisible(hwnd):
                return True
            out.append((int(hwnd), _window_text(hwnd)))
            return True

        try:
            _user32.EnumDesktopWindows(hdesk, _WNDENUMPROC(_cb), 0)
        finally:
            close_desktop(hdesk)
        return out

    def _window_text(hwnd: int) -> str:
        n = _user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def post_click(hwnd: int) -> None:
        """消息级点击按钮控件（BM_CLICK，不移动鼠标、不抢焦点）。"""
        _user32.SendMessageW(hwnd, BM_CLICK, 0, 0)

    def set_text(hwnd: int, text: str) -> None:
        """消息级写入文本（WM_SETTEXT）。"""
        buf = ctypes.create_unicode_buffer(text)
        _user32.SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.cast(buf, ctypes.c_void_p).value)

    def get_text(hwnd: int) -> str:
        """消息级读取文本（WM_GETTEXT）。"""
        n = _user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, ctypes.cast(buf, ctypes.c_void_p).value)
        return buf.value

    def close_window(hwnd: int) -> None:
        _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

else:  # 非 Windows：占位实现，import 无副作用，调用即明确报错（引导退回 dry-run）
    def _unavailable(*_a, **_k):  # noqa: ANN001
        raise RuntimeError("win_desktop 仅在 Windows guest 内可用（当前平台无隔离桌面能力）")

    ensure_desktop = _unavailable  # type: ignore[assignment]
    close_desktop = _unavailable  # type: ignore[assignment]
    launch_on_desktop = _unavailable  # type: ignore[assignment]
    enum_windows = _unavailable  # type: ignore[assignment]
    post_click = _unavailable  # type: ignore[assignment]
    set_text = _unavailable  # type: ignore[assignment]
    get_text = _unavailable  # type: ignore[assignment]
    close_window = _unavailable  # type: ignore[assignment]

    @contextmanager
    def attached(name: str) -> Iterator[int]:  # type: ignore[misc]
        raise RuntimeError("win_desktop.attached 仅在 Windows guest 内可用")
        yield 0  # pragma: no cover
