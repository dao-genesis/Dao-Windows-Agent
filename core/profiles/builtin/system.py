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
import urllib.request

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


def _download(adapter, instance, url: str, path: str, timeout: int = 300, **_):
    """下载 URL 到磁盘文件（纯 stdlib，自动建父目录）——软件分发/资源获取入口。"""
    if not url or not path:
        return ActionResult.bad("需提供 url 与 path")
    parent = os.path.dirname(os.path.abspath(path))
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "dao-windows-agent"})
        with urllib.request.urlopen(req, timeout=int(timeout)) as resp, open(path, "wb") as fh:
            total = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                total += len(chunk)
    except (OSError, ValueError) as exc:
        return ActionResult.bad(f"{type(exc).__name__}: {exc}")
    return ActionResult.good({"url": url, "path": os.path.abspath(path), "bytes": total})


def _install_pkg(adapter, instance, pkg: str, source: str = "winget", timeout: int = 900, **_):
    """安装软件（Windows→winget，静默接受协议）。"""
    if not pkg:
        return ActionResult.bad("需提供 pkg（winget 包 id，如 Git.Git）")
    if not _IS_WIN:
        return ActionResult.bad("install_pkg 仅 Windows(winget)；类 Unix 请直接 exec 包管理器命令")
    if source != "winget":
        return ActionResult.bad(f"未知 source: {source}（目前仅 winget）")
    cmd = (f"winget install --id {pkg} -e --source winget --silent "
           "--accept-package-agreements --accept-source-agreements "
           "--disable-interactivity")
    return adapter.run_cli(_shell_cmd(cmd), instance, timeout=int(timeout))


def _service(adapter, instance, action: str = "list", name: str = "", timeout: int = 180, **_):
    """Windows 服务：list/query/start/stop（PowerShell *-Service）。"""
    action = (action or "list").lower()
    if action not in ("list", "query", "start", "stop", "restart"):
        return ActionResult.bad(f"未知 action: {action}")
    if not _IS_WIN:
        return ActionResult.bad("service 仅 Windows；类 Unix 请 exec systemctl")
    if action == "list":
        cmd = "Get-Service | Sort-Object Status,Name | Format-Table -AutoSize Status,Name,DisplayName"
    else:
        if not name:
            return ActionResult.bad("需提供 name")
        verb = {"query": "Get", "start": "Start", "stop": "Stop", "restart": "Restart"}[action]
        cmd = f"{verb}-Service -Name '{name}'" + (" | Format-List *" if action == "query" else "; Get-Service -Name '" + name + "'")
    return adapter.run_cli(_shell_cmd(cmd), instance, timeout=int(timeout))


def _registry(adapter, instance, action: str = "read", path: str = "", name: str = "",
              value: str = "", reg_type: str = "REG_SZ", timeout: int = 60, **_):
    """注册表：read/write/delete（reg.exe，例 path=HKCU\\Software\\Dao）。"""
    action = (action or "read").lower()
    if action not in ("read", "write", "delete"):
        return ActionResult.bad(f"未知 action: {action}")
    if not path:
        return ActionResult.bad("需提供 path（如 HKCU\\Software\\Dao）")
    if not _IS_WIN:
        return ActionResult.bad("registry 仅 Windows")
    if action == "read":
        cmd = f'reg query "{path}"' + (f' /v "{name}"' if name else "")
    elif action == "write":
        if not name:
            return ActionResult.bad("write 需提供 name")
        cmd = f'reg add "{path}" /v "{name}" /t {reg_type} /d "{value}" /f'
    else:
        cmd = f'reg delete "{path}"' + (f' /v "{name}"' if name else "") + " /f"
    return adapter.run_cli(_shell_cmd(cmd), instance, timeout=int(timeout))


def _schtask(adapter, instance, action: str = "list", name: str = "", cmd: str = "",
             schedule: str = "ONCE", start_time: str = "", timeout: int = 60, **_):
    """计划任务：list/create/run/delete（schtasks.exe）。"""
    action = (action or "list").lower()
    if action not in ("list", "create", "run", "delete"):
        return ActionResult.bad(f"未知 action: {action}")
    if not _IS_WIN:
        return ActionResult.bad("schtask 仅 Windows；类 Unix 请 exec crontab")
    if action == "list":
        line = "schtasks /query /fo LIST" + (f' /tn "{name}"' if name else "")
    elif action == "create":
        if not name or not cmd:
            return ActionResult.bad("create 需提供 name 与 cmd")
        line = f'schtasks /create /f /tn "{name}" /tr "{cmd}" /sc {schedule}'
        if start_time:
            line += f" /st {start_time}"
    elif action == "run":
        if not name:
            return ActionResult.bad("run 需提供 name")
        line = f'schtasks /run /tn "{name}"'
    else:
        if not name:
            return ActionResult.bad("delete 需提供 name")
        line = f'schtasks /delete /f /tn "{name}"'
    return adapter.run_cli(_shell_cmd(line), instance, timeout=int(timeout))


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
    layer="universal",
    mention="win",
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
        Verb("download", "下载 URL 到磁盘文件(纯 stdlib·自动建父目录)",
             {"url": "源地址", "path": "落盘路径", "timeout": "秒(默认300)"},
             handler=_download, aliases=("fetch", "wget", "curl")),
        Verb("install_pkg", "安装软件(Windows→winget·静默接受协议)",
             {"pkg": "winget 包 id(如 Git.Git)", "source": "默认 winget", "timeout": "秒(默认900)"},
             handler=_install_pkg, aliases=("winget", "install")),
        Verb("service", "Windows 服务 list/query/start/stop/restart(PowerShell *-Service)",
             {"action": "list|query|start|stop|restart", "name": "服务名(非 list 必填)"},
             handler=_service, aliases=("services", "sc")),
        Verb("registry", "注册表 read/write/delete(reg.exe)",
             {"action": "read|write|delete", "path": "如 HKCU\\Software\\Dao", "name": "值名",
              "value": "写入值", "reg_type": "REG_SZ/REG_DWORD 等"},
             handler=_registry, aliases=("reg",)),
        Verb("schtask", "计划任务 list/create/run/delete(schtasks.exe)",
             {"action": "list|create|run|delete", "name": "任务名", "cmd": "create 时的命令行",
              "schedule": "ONCE/DAILY 等(默认 ONCE)", "start_time": "HH:MM(可选)"},
             handler=_schtask, aliases=("task", "schtasks")),
    ],
)
_ADAPTER = SubprocessApiAdapter
