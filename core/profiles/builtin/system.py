"""整机系统画像（级别① · 无头 shell/文件/进程 · "把整台机器做进 IDE" 的底座）。

这是"路由整个 Windows 进 IDE、与用户账号完全复刻"的最底层能力面——对标你（Agent）
在自己 Linux 虚拟机里能做的一切：跑命令、读写文件、列目录、看进程、查环境。级别①、无头、
天然隔离并行（不上任何可见桌面、不抢焦点），Windows guest 与 Linux 宿主同构可跑。

跨平台：`exec` 在 Windows 走 PowerShell、在类 Unix 走 /bin/sh —— 故 Linux/CI 也能真跑真测，
不必等 Windows 真机（守约：core 纯 stdlib、无第三方依赖）。文件/目录动词用纯 Python 实现，
不经 shell，稳定可移植。
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys

from core.adapter.base import ActionResult
from core.adapter.subprocess_api import SubprocessApiAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb

_IS_WIN = sys.platform == "win32"


def _shell_cmd(cmd: str) -> list[str]:
    """把一行命令包成当前平台的 shell 调用。"""
    if _IS_WIN:
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    return ["/bin/sh", "-c", cmd]


def _exec(adapter, instance, cmd: str, timeout: int = 120, **_):
    """在会话工作目录内执行一行 shell 命令（Windows→PowerShell / Unix→sh），回传输出。"""
    if not cmd:
        return ActionResult.bad("需提供 cmd")
    return adapter.run_cli(_shell_cmd(cmd), instance, timeout=int(timeout))


def _read_file(adapter, instance, path: str, max_bytes: int = 1_000_000, **_):
    """读取文本文件内容（默认上限 1MB，防爆内存）。"""
    if not path:
        return ActionResult.bad("需提供 path")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read(int(max_bytes) + 1)
    except OSError as exc:
        return ActionResult.bad(f"{type(exc).__name__}: {exc}")
    truncated = len(data) > int(max_bytes)
    return ActionResult.good({"path": path, "content": data[: int(max_bytes)], "truncated": truncated})


def _write_file(adapter, instance, path: str, content: str = "", append: bool = False, **_):
    """写入文本文件（append=True 追加）；自动建父目录。"""
    if not path:
        return ActionResult.bad("需提供 path")
    parent = os.path.dirname(os.path.abspath(path))
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a" if append else "w", encoding="utf-8") as fh:
            n = fh.write(content or "")
    except OSError as exc:
        return ActionResult.bad(f"{type(exc).__name__}: {exc}")
    return ActionResult.good({"path": path, "written": n, "append": bool(append)})


def _list_dir(adapter, instance, path: str = ".", **_):
    """列目录（返回条目名、是否目录、大小）。"""
    try:
        entries = []
        with os.scandir(path) as it:
            for e in it:
                try:
                    size = e.stat().st_size
                except OSError:
                    size = -1
                entries.append({"name": e.name, "is_dir": e.is_dir(), "size": size})
    except OSError as exc:
        return ActionResult.bad(f"{type(exc).__name__}: {exc}")
    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return ActionResult.good({"path": os.path.abspath(path), "entries": entries})


def _processes(adapter, instance, name_contains: str = "", **_):
    """列出进程（Windows→tasklist / Unix→ps）；可按名过滤。"""
    args = ["tasklist"] if _IS_WIN else ["ps", "-eo", "pid,comm,pcpu,pmem"]
    res = adapter.run_cli(args, instance, timeout=30)
    if res.ok and name_contains and isinstance(res.value, dict):
        lines = [ln for ln in res.value.get("stdout", "").splitlines()
                 if name_contains.lower() in ln.lower()]
        res.value["filtered"] = lines
    return res


def _env(adapter, instance, name: str = "", **_):
    """读取环境变量（给 name 取单个，否则全量）。"""
    if name:
        return ActionResult.good({name: os.environ.get(name)})
    return ActionResult.good(dict(os.environ))


def _sysinfo(adapter, instance, **_):
    """整机身份/系统信息（对照"复刻用户账号所在机器"）。"""
    return ActionResult.good({
        "platform": platform.platform(),
        "node": platform.node(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
        "cwd": os.getcwd(),
        "home": os.path.expanduser("~"),
    })


PROFILE = AppProfile(
    app_id="system",
    display_name="整机系统 (Shell/文件/进程 · 级别①底座)",
    level=AutomationLevel.API,
    launch={"headless": True},
    file_conventions={"outputs": ["any"]},
    source_repo="本仓（整机底座；对标 devin-remote 机控桥的 /api/exec·/api/file·/api/ls）",
    tags=("system", "shell", "headless", "level1", "整机"),
    prompt_snippet=(
        "整机系统画像是级别①底座：跑命令(exec)、读写文件、列目录、看进程、查环境——"
        "把整台 Windows 当作你自己的机器操作，与用户真实桌面并行、无头、天然隔离。"
        "凡能经 shell/文件/CLI 达成的，一律走本画像（绝不上级别②③）。"
    ),
    verbs=[
        Verb("exec", "执行一行 shell 命令(Windows→PowerShell/Unix→sh)，回传 stdout",
             {"cmd": "命令行", "timeout": "秒(默认120)"}, handler=_exec,
             aliases=("run", "shell", "cmd")),
        Verb("read_file", "读出磁盘文件文本",
             {"path": "文件路径", "max_bytes": "读取上限(默认1MB)"}, handler=_read_file,
             aliases=("cat",)),
        Verb("write_file", "写入/追加文本文件(自动建父目录)",
             {"path": "文件路径", "content": "内容", "append": "是否追加"}, handler=_write_file,
             aliases=("write",)),
        Verb("list_dir", "列目录条目(名/是否目录/大小)",
             {"path": "目录(默认.)"}, handler=_list_dir, aliases=("ls", "dir")),
        Verb("processes", "列出进程(可按名过滤)",
             {"name_contains": "名称子串过滤"}, handler=_processes, aliases=("ps", "tasklist")),
        Verb("env", "读取环境变量(给 name 取单个,否则全量)",
             {"name": "变量名(可选)"}, handler=_env, aliases=("getenv",)),
        Verb("sysinfo", "整机身份/系统信息(平台/主机名/用户/家目录)", handler=_sysinfo,
             aliases=("whoami", "info")),
    ],
)
_ADAPTER = SubprocessApiAdapter
