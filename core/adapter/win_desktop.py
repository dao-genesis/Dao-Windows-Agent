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
CREATE_UNICODE_ENVIRONMENT = 0x00000400

# 令牌/会话（供 SYSTEM(session0) 桥用交互会话令牌起隔离桌面进程）
MAXIMUM_ALLOWED = 0x02000000
SECURITY_IMPERSONATION = 2  # SECURITY_IMPERSONATION_LEVEL
TOKEN_PRIMARY = 1           # TOKEN_TYPE
ERROR_ACCESS_DENIED = 5
SECURITY_DESCRIPTOR_REVISION = 1

# 窗口消息（消息级输入，不抢焦点）
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CHAR = 0x0102
EM_SETSEL = 0x00B1
EM_REPLACESEL = 0x00C2
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
BM_CLICK = 0x00F5
WM_CLOSE = 0x0010

# PrintWindow：把窗口自绘到位图 → 跨桌面取图（隔离桌面非输入桌面，屏幕 DC 截不到，
# 但 PrintWindow 让窗口自己画，故隔离桌面上的窗口也能取证）。
PW_RENDERFULLCONTENT = 0x00000002

# 编辑区常见类名（新老通吃）：Win11 现代记事本是 RichEditD2DPT，经典程序是 Edit。
_EDIT_CLASSES = (
    "RichEditD2DPT", "Edit", "RichEdit20W", "RichEdit50W",
    "RICHEDIT60W", "NotepadTextBox", "RichEdit20A",
)


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

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", wintypes.BOOL),
        ]

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _advapi32.InitializeSecurityDescriptor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    _advapi32.InitializeSecurityDescriptor.restype = wintypes.BOOL
    _advapi32.SetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, wintypes.BOOL, ctypes.c_void_p, wintypes.BOOL,
    ]
    _advapi32.SetSecurityDescriptorDacl.restype = wintypes.BOOL
    _advapi32.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_int,
        ctypes.c_int, ctypes.POINTER(wintypes.HANDLE),
    ]
    _advapi32.DuplicateTokenEx.restype = wintypes.BOOL
    _advapi32.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p,
        wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    _advapi32.CreateProcessAsUserW.restype = wintypes.BOOL

    _wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    _wtsapi32.WTSQueryUserToken.argtypes = [wintypes.ULONG, ctypes.POINTER(wintypes.HANDLE)]
    _wtsapi32.WTSQueryUserToken.restype = wintypes.BOOL

    _userenv = ctypes.WinDLL("userenv", use_last_error=True)
    _userenv.CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.BOOL]
    _userenv.CreateEnvironmentBlock.restype = wintypes.BOOL
    _userenv.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]
    _userenv.DestroyEnvironmentBlock.restype = wintypes.BOOL

    _kernel32.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD
    _kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    _kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

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
    _user32.EnumChildWindows.argtypes = [wintypes.HWND, _WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumChildWindows.restype = wintypes.BOOL
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _user32.PrintWindow.restype = wintypes.BOOL

    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
    ]
    _gdi32.GetDIBits.restype = ctypes.c_int

    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION),
    ]
    _kernel32.CreateProcessW.restype = wintypes.BOOL

    def _open_dacl_sa() -> "ctypes.pointer":
        """构造一个带 NULL DACL（人人可访问）的 SECURITY_ATTRIBUTES。

        桥以 SYSTEM 起桌面、却要用**交互会话用户令牌**在其上起进程时，桌面对象默认 DACL
        不含该用户 → CreateProcessAsUser 报 ERROR_ACCESS_DENIED(5)。给桌面一个开放 DACL，
        任何主体皆可访问，闭合"单账号内 SYSTEM 造桌面、用户令牌用之"的隔离链路。
        对单账号零配置隔离场景无额外风险（本就同一用户上下文）。
        """
        # SECURITY_DESCRIPTOR（绝对格式）在 x64 上是 40 字节（4 头 + 4 指针×8），
        # 20 字节缓冲会被 Initialize/SetDacl 写越界 → 堆损坏 → 后续调用 ERROR_NOACCESS(998)。
        sd = ctypes.create_string_buffer(64)
        if not _advapi32.InitializeSecurityDescriptor(sd, SECURITY_DESCRIPTOR_REVISION):
            raise ctypes.WinError(ctypes.get_last_error())
        # bDaclPresent=True, pDacl=NULL, bDaclDefaulted=False → NULL DACL = 允许所有访问
        if not _advapi32.SetSecurityDescriptorDacl(sd, True, None, False):
            raise ctypes.WinError(ctypes.get_last_error())
        sa = SECURITY_ATTRIBUTES()
        sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
        sa.lpSecurityDescriptor = ctypes.cast(sd, ctypes.c_void_p)
        sa.bInheritHandle = False
        sa._sd_keepalive = sd  # 防 sd 缓冲被 GC（sa 持有其指针）
        return sa

    def ensure_desktop(name: str) -> int:
        """打开同名桌面；不存在则以开放 DACL 创建。返回 HDESK（int）。失败抛 OSError。"""
        name = sanitize_name(name)
        h = _user32.OpenDesktopW(name, 0, False, DESKTOP_ALL)
        if not h:
            sa = _open_dacl_sa()
            h = _user32.CreateDesktopW(name, None, None, 0, DESKTOP_ALL, ctypes.byref(sa))
        if not h:
            raise ctypes.WinError(ctypes.get_last_error())
        return h

    def _in_session_zero() -> bool:
        """当前进程是否在 session 0（SYSTEM 服务会话，起不了交互/隔离桌面进程）。"""
        sid = wintypes.DWORD(0)
        if _kernel32.ProcessIdToSessionId(_kernel32.GetCurrentProcessId(), ctypes.byref(sid)):
            return sid.value == 0
        return False

    def close_desktop(hdesk: int) -> None:
        if hdesk:
            _user32.CloseDesktop(hdesk)

    @contextmanager
    def attached(name: str) -> Iterator[int]:
        """尽力把**当前线程**绑到隔离桌面；绑不上也照常放行（best-effort）。

        本模块所有原语均**按句柄直达**（EnumDesktopWindows 走 hdesk、launch 走
        lpDesktop、输入/取图走 hwnd 消息级），并不依赖线程桌面绑定。SetThreadDesktop
        只是锦上添花（让第三方 UIA 之类的"当前桌面"查询也指向隔离桌面），而它要求
        调用线程当前没有任何窗口/hook（否则 ERROR_BUSY=170）——如 Python 主线程常
        因宿主已挂窗口而绑不上。故：能绑则绑、绑不上不拦路，退出时还原。
        """
        hdesk = ensure_desktop(name)
        prev = _user32.GetThreadDesktop(_kernel32.GetCurrentThreadId())
        bound = bool(_user32.SetThreadDesktop(hdesk))
        try:
            yield hdesk
        finally:
            if bound and prev:
                _user32.SetThreadDesktop(prev)
            close_desktop(hdesk)

    def _new_startupinfo(name: str) -> "STARTUPINFOW":
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(STARTUPINFOW)
        si.lpDesktop = name  # ← 关键：老路用 subprocess 无法设此字段，进程遂落默认桌面
        si.dwFlags = STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOWNORMAL
        return si

    def launch_on_desktop_as_user(name: str, cmdline: str, workdir: Optional[str] = None) -> int:
        """以**当前活动交互会话的用户令牌**把进程起到隔离桌面（供 SYSTEM 桥用）。返回 pid。

        闭合"桥跑在 session 0(SYSTEM) 却要起隔离桌面交互进程"这一环：session 0 直接
        CreateProcessW 起交互进程受限（ERROR_ACCESS_DENIED=5）；正解是拿活动控制台会话
        的用户令牌、DuplicateTokenEx 成主令牌后 CreateProcessAsUser 起到隔离桌面。
        需调用方具 SYSTEM 权限（WTSQueryUserToken 要求），否则抛错由上层退回直起。
        """
        name = sanitize_name(name)
        ensure_desktop(name)
        console_sid = _kernel32.WTSGetActiveConsoleSessionId()
        if console_sid == 0xFFFFFFFF:
            raise OSError("无活动控制台会话（无人登录），无法取用户令牌")
        htok = wintypes.HANDLE()
        if not _wtsapi32.WTSQueryUserToken(console_sid, ctypes.byref(htok)):
            raise ctypes.WinError(ctypes.get_last_error())
        hdup = wintypes.HANDLE()
        env = ctypes.c_void_p()
        try:
            if not _advapi32.DuplicateTokenEx(
                htok, MAXIMUM_ALLOWED, None, SECURITY_IMPERSONATION, TOKEN_PRIMARY,
                ctypes.byref(hdup),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            flags = NORMAL_PRIORITY_CLASS
            if _userenv.CreateEnvironmentBlock(ctypes.byref(env), hdup, False):
                flags |= CREATE_UNICODE_ENVIRONMENT
            else:
                env = ctypes.c_void_p()  # 取不到就用调用方环境
            si = _new_startupinfo(name)
            pi = PROCESS_INFORMATION()
            buf = ctypes.create_unicode_buffer(cmdline)
            ok = _advapi32.CreateProcessAsUserW(
                hdup, None, buf, None, None, False, flags,
                env if env else None, workdir, ctypes.byref(si), ctypes.byref(pi),
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
            _kernel32.CloseHandle(pi.hThread)
            _kernel32.CloseHandle(pi.hProcess)
            return int(pi.dwProcessId)
        finally:
            if env:
                _userenv.DestroyEnvironmentBlock(env)
            if hdup:
                _kernel32.CloseHandle(hdup)
            _kernel32.CloseHandle(htok)

    def launch_on_desktop(name: str, cmdline: str, workdir: Optional[str] = None) -> int:
        """把进程真正起到隔离桌面（STARTUPINFOW.lpDesktop）。返回 pid。

        cmdline 传完整命令行（可含参数），如 'notepad.exe C:\\a.txt'。
        会话自适应：在 session 0（SYSTEM 服务）内直起交互进程会被拒，故先尝试取活动会话
        用户令牌走 CreateProcessAsUser；非 session 0 或取令牌失败则回退直起 CreateProcessW。
        """
        name = sanitize_name(name)
        ensure_desktop(name)  # 保证桌面存在（开放 DACL）
        if _in_session_zero():
            try:
                return launch_on_desktop_as_user(name, cmdline, workdir)
            except OSError:
                pass  # 取令牌/起进程失败 → 回退直起（下方），由上层看真错误
        si = _new_startupinfo(name)
        pi = PROCESS_INFORMATION()
        buf = ctypes.create_unicode_buffer(cmdline)  # 可写缓冲（CreateProcessW 要求）
        ok = _kernel32.CreateProcessW(
            None, buf, None, None, False, NORMAL_PRIORITY_CLASS, None, workdir,
            ctypes.byref(si), ctypes.byref(pi),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
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

    def replace_text(hwnd: int, text: str) -> None:
        """全选后消息级替换文本，兼容拒绝 WM_SETTEXT 的 RichEdit 实现。"""
        buf = ctypes.create_unicode_buffer(text)
        _user32.SendMessageW(hwnd, EM_SETSEL, 0, -1)
        _user32.SendMessageW(
            hwnd, EM_REPLACESEL, 1, ctypes.cast(buf, ctypes.c_void_p).value)

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

    def _class_name(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def list_children(hwnd: int) -> List[Tuple[int, str, str]]:
        """枚举窗口的**全部后代**控件，返回 [(hwnd, class_name, text), ...]。

        EnumChildWindows 本身即递归枚举所有后代（含孙辈），无需手动下钻。
        """
        out: List[Tuple[int, str, str]] = []

        def _cb(child, _lparam):
            out.append((int(child), _class_name(child), _window_text(child)))
            return True

        _user32.EnumChildWindows(hwnd, _WNDENUMPROC(_cb), 0)
        return out

    def find_edit_control(hwnd: int, classes: Tuple[str, ...] = _EDIT_CLASSES) -> Optional[int]:
        """在窗口后代里找主编辑控件（按 classes 优先级）；找不到返回 None。

        新老通吃：Win11 现代记事本编辑区是 RichEditD2DPT，经典程序是 Edit。消息级
        WM_SETTEXT/WM_GETTEXT 对二者均生效且**不抢焦点、跨桌面有效**。
        """
        kids = list_children(hwnd)
        for want in classes:
            for h, cls, _t in kids:
                if cls.casefold() == want.casefold():
                    return h
        for h, cls, _t in kids:
            if cls.casefold().startswith("richedit"):
                return h
        return None

    def window_process_id(hwnd: int) -> int:
        """返回顶层窗口所属进程 id。"""
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def find_top_window(name: str, title_contains: Optional[str] = None,
                        class_name: Optional[str] = None) -> Optional[int]:
        """在隔离桌面顶层窗口里按标题子串/类名定位一个窗口 hwnd；取最新（最后枚举到的）。"""
        match: Optional[int] = None
        for h, title in enum_windows(name):
            if title_contains and title_contains.lower() not in title.lower():
                continue
            if class_name and _class_name(h) != class_name:
                continue
            match = h
        return match

    def send_chars(hwnd: int, text: str) -> None:
        """逐字符 WM_CHAR 送入控件（消息级，不抢焦点）；供不吃 WM_SETTEXT 的控件用。"""
        for ch in text:
            _user32.SendMessageW(hwnd, WM_CHAR, ord(ch), 0)

    def capture_window(hwnd: int, path: str) -> str:
        """PrintWindow 把窗口自绘到位图并存 BMP → 跨桌面取证（隔离桌面非输入桌面也可）。

        存为 24 位 BMP（stdlib 可写、无需 Pillow）。返回落盘路径。
        """
        import struct

        rect = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            raise OSError("窗口尺寸无效，无法截图")
        screen_dc = _user32.GetDC(0)
        mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
        bmp = _gdi32.CreateCompatibleBitmap(screen_dc, w, h)
        old = _gdi32.SelectObject(mem_dc, bmp)
        try:
            if not _user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT):
                _user32.PrintWindow(hwnd, mem_dc, 0)
            # BITMAPINFOHEADER：负高度=自上而下
            hdr = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 24, 0, 0, 0, 0, 0, 0)
            row = (w * 3 + 3) & ~3
            buf = ctypes.create_string_buffer(row * h)
            _gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, hdr, 0)
            file_hdr = struct.pack("<2sIHHI", b"BM", 14 + 40 + row * h, 0, 0, 14 + 40)
            info_hdr = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, row * h, 0, 0, 0, 0)
            # 自上而下的像素需翻转为 BMP 的自下而上
            rows = [buf.raw[i * row:(i + 1) * row] for i in range(h)]
            body = b"".join(reversed(rows))
            with open(path, "wb") as f:
                f.write(file_hdr + info_hdr + body)
        finally:
            _gdi32.SelectObject(mem_dc, old)
            _gdi32.DeleteObject(bmp)
            _gdi32.DeleteDC(mem_dc)
            _user32.ReleaseDC(0, screen_dc)
        return path

else:  # 非 Windows：占位实现，import 无副作用，调用即明确报错（引导退回 dry-run）
    def _unavailable(*_a, **_k):  # noqa: ANN001
        raise RuntimeError("win_desktop 仅在 Windows guest 内可用（当前平台无隔离桌面能力）")

    ensure_desktop = _unavailable  # type: ignore[assignment]
    close_desktop = _unavailable  # type: ignore[assignment]
    launch_on_desktop = _unavailable  # type: ignore[assignment]
    launch_on_desktop_as_user = _unavailable  # type: ignore[assignment]
    enum_windows = _unavailable  # type: ignore[assignment]
    post_click = _unavailable  # type: ignore[assignment]
    set_text = _unavailable  # type: ignore[assignment]
    replace_text = _unavailable  # type: ignore[assignment]
    get_text = _unavailable  # type: ignore[assignment]
    close_window = _unavailable  # type: ignore[assignment]
    list_children = _unavailable  # type: ignore[assignment]
    find_edit_control = _unavailable  # type: ignore[assignment]
    window_process_id = _unavailable  # type: ignore[assignment]
    find_top_window = _unavailable  # type: ignore[assignment]
    send_chars = _unavailable  # type: ignore[assignment]
    capture_window = _unavailable  # type: ignore[assignment]

    @contextmanager
    def attached(name: str) -> Iterator[int]:  # type: ignore[misc]
        raise RuntimeError("win_desktop.attached 仅在 Windows guest 内可用")
        yield 0  # pragma: no cover
