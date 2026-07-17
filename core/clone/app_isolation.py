"""按分身号派生"应用层隔离启动规格"（纯逻辑·可离线单测）。

核心洞察（真机实测取证）：
    单账号多 RDP 分身，RDP 会话层已隔离，但 Electron/Chromium 系应用（VS Code、
    Devin Desktop、Chrome、Edge…）的**单实例锁是 per-user**——锁/命名管道落在共享的
    `%APPDATA%` 或固定命名对象里。于是第二个分身启动同一软件时，启动请求被转发给
    第一个分身已在运行的实例，新窗口开到了**第一个分身的会话**里，第二个分身什么也没得到。
    实测：分身1(session2)、分身2(session3) 先后 `code`，结果 11 个 Code 进程全落在
    session2、session3 只剩一个 crashpad——正是用户所述"缠在一起、无法隔离"。

根治：给每个分身派生独立 `user-data-dir`（Electron/Chromium）或独立用户配置目录
    （FreeCAD 等），单实例锁作用域即从 per-user 收窄到 per-clone，多分身开同一软件
    各自成实例、互不串扰。派生目录形如 `C:\\dao_clones\\<clone_id>\\<app>`。

诚实边界：
    - 本策略只对"有 user-data-dir / 用户配置目录开关或对应环境变量"的软件零配置奏效。
    - 完全无任何隔离开关、且把单实例互斥体钉死在全局命名空间的软件，单账号零配置隔离
      是 Windows 固有约束（AGENTS.md 三节），需退回 CreateDesktop 消息级或独立账号——
      本模块对这类软件如实返回 `isolatable=False`，绝不假装能隔离。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# 分身派生目录根（guest 内）。用反斜杠是因为落地方是 Windows。
DEFAULT_ROOT = r"C:\dao_clones"


def clone_data_root(clone_id: str, app_id: str, root: str = DEFAULT_ROOT) -> str:
    """派生某分身某软件的独立数据目录，如 C:\\dao_clones\\session-3\\vscode。"""
    return f"{root}\\{_safe(clone_id)}\\{_safe(app_id)}"


def _safe(token: str) -> str:
    """净化分身号/软件名为安全的路径片段：仅留字母数字/下划线/连字符/点。

    分身号可能来自会话 id、账号名甚至外部输入；不净化会导致路径穿越或命令拼接。
    """
    token = (token or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", token)
    cleaned = cleaned.strip("._-") or "default"
    return cleaned[:64]


@dataclass(frozen=True)
class IsolationStrategy:
    """一类软件的分身隔离策略。"""

    app_id: str
    # 可执行文件候选（guest 内绝对路径/命令名，落地方按序探测第一处存在者）。
    exe_candidates: List[str]
    # 由分身数据目录派生附加启动参数（如 --user-data-dir=<dir>）。
    args_from_dir: Callable[[str], List[str]] = field(default=lambda d: [])
    # 由分身数据目录派生附加环境变量（如 FreeCAD 的 FREECAD_USER_HOME）。
    env_from_dir: Callable[[str], Dict[str, str]] = field(default=lambda d: {})
    # 该软件单实例锁能否被上述手段收窄到 per-clone。
    isolatable: bool = True
    # 启动前需预建的子目录（真机取证：Notepad++ 的 -settingsDir 目录不存在则静默回退共享 %APPDATA%）。
    dirs_from_dir: Callable[[str], List[str]] = field(default=lambda d: [])
    # 备注：隔离机理，供文档/诊断。
    note: str = ""


@dataclass(frozen=True)
class CloneLaunchSpec:
    """一次分身内隔离启动的完整规格（落地方据此 Start-Process）。"""

    app_id: str
    clone_id: str
    exe_candidates: List[str]
    args: List[str]
    env: Dict[str, str]
    data_dir: str
    isolatable: bool
    note: str
    # 落地方 Start-Process 前需预建的目录（含 data_dir 本身）。
    pre_create: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "app_id": self.app_id,
            "clone_id": self.clone_id,
            "exe_candidates": list(self.exe_candidates),
            "args": list(self.args),
            "env": dict(self.env),
            "data_dir": self.data_dir,
            "isolatable": self.isolatable,
            "note": self.note,
            "pre_create": list(self.pre_create),
        }


def _electron_user_data(dir_: str) -> List[str]:
    # Electron/Chromium：--user-data-dir 决定单实例锁与命名管道的作用域。
    return [f"--user-data-dir={dir_}\\data"]


def _vscode_args(dir_: str) -> List[str]:
    # VS Code 家族：另隔离扩展目录，避免分身间扩展状态互相污染。
    return [f"--user-data-dir={dir_}\\data", f"--extensions-dir={dir_}\\ext"]


def _ide_clone_env(dir_: str) -> Dict[str, str]:
    # Devin Desktop 插件版(dao-desktop)的环境共生检测读此变量：IDE 层配置随分身走，
    # 引擎层(~/.codeium)仍全分身共生——Windows Agent 体系与插件体系的对接点。
    return {"DAO_CLONE_USER_DATA_DIR": f"{dir_}\\data"}


def _freecad_env(dir_: str) -> Dict[str, str]:
    # FreeCAD 从 FREECAD_USER_HOME 读取用户配置根；分身各自一份即不再互相覆盖偏好。
    return {"FREECAD_USER_HOME": f"{dir_}\\home"}


def _npp_args(dir_: str) -> List[str]:
    # Notepad++：-multiInst 绕过单实例转发；-settingsDir 把配置根收窄到 per-clone。
    return ["-multiInst", f"-settingsDir={dir_}\\settings"]


def _npp_dirs(dir_: str) -> List[str]:
    # 真机取证：-settingsDir 目录不存在时 Notepad++ 静默回退共享 %APPDATA%（隔离失效）。
    return [f"{dir_}\\settings"]


def _vlc_args(dir_: str) -> List[str]:
    # VLC：--no-one-instance 绕过单实例转发；--config 指定 per-clone 的 vlcrc。
    return ["--no-one-instance", f"--config={dir_}\\vlcrc"]


def _sumatra_args(dir_: str) -> List[str]:
    # SumatraPDF：-appdata 把设置/缓存目录收窄到 per-clone；-new-window 绕过既有窗口复用。
    return ["-appdata", f"{dir_}\\appdata", "-new-window"]


def _firefox_args(dir_: str) -> List[str]:
    # Firefox：-no-remote 绕过 remoting 单实例转发；-profile 独立画像目录（经典全隔离）。
    return ["-no-remote", "-profile", f"{dir_}\\profile"]


def _inkscape_env(dir_: str) -> Dict[str, str]:
    # INKSCAPE_PROFILE_DIR 把偏好/扩展收窄到 per-clone。
    return {"INKSCAPE_PROFILE_DIR": f"{dir_}\\profile"}


def _inkscape_args(dir_: str) -> List[str]:
    # 真机取证：Inkscape 1.x 是 GApplication 单实例（第二个启动被转发后退出）；
    # --app-id-tag 把 D-Bus 应用 id 收窄到 per-clone，分身各自成实例。
    tag = "dao_" + re.sub(r"[^A-Za-z0-9]", "_", dir_)[-48:].strip("_")
    return [f"--app-id-tag={tag}"]


ISOLATION_REGISTRY: Dict[str, IsolationStrategy] = {
    "vscode": IsolationStrategy(
        app_id="vscode",
        exe_candidates=[
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        ],
        args_from_dir=_vscode_args,
        env_from_dir=_ide_clone_env,
        note="Electron 单实例锁在 user-data-dir 内，分身各自一份即独立实例",
    ),
    "devin-desktop": IsolationStrategy(
        app_id="devin-desktop",
        exe_candidates=[
            r"%LOCALAPPDATA%\Programs\Devin\Devin.exe",
            r"%LOCALAPPDATA%\Programs\Windsurf\Windsurf.exe",
            r"C:\Program Files\Devin\Devin.exe",
            r"C:\Program Files\Windsurf\Windsurf.exe",
        ],
        args_from_dir=_vscode_args,
        env_from_dir=_ide_clone_env,
        note="Devin Desktop = VS Code/Electron 内核，隔离方式同 vscode",
    ),
    "chrome": IsolationStrategy(
        app_id="chrome",
        exe_candidates=[
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        args_from_dir=_electron_user_data,
        note="Chromium 单实例锁在 user-data-dir 内",
    ),
    "edge": IsolationStrategy(
        app_id="edge",
        exe_candidates=[
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        args_from_dir=_electron_user_data,
        note="Chromium 单实例锁在 user-data-dir 内",
    ),
    "freecad": IsolationStrategy(
        app_id="freecad",
        exe_candidates=[
            r"C:\Program Files\FreeCAD 1.0\bin\FreeCAD.exe",
            r"%LOCALAPPDATA%\Programs\FreeCAD 1.0\bin\FreeCAD.exe",
        ],
        env_from_dir=_freecad_env,
        note="FreeCAD 默认允许多开，另隔离 FREECAD_USER_HOME 避免分身间偏好互相覆盖",
    ),
    "notepadpp": IsolationStrategy(
        app_id="notepadpp",
        exe_candidates=[
            r"C:\Program Files\Notepad++\notepad++.exe",
            r"C:\Program Files (x86)\Notepad++\notepad++.exe",
        ],
        args_from_dir=_npp_args,
        dirs_from_dir=_npp_dirs,
        note="单实例转发经 -multiInst 绕过；-settingsDir 收窄配置根到 per-clone（目录须预建，否则静默回退共享 %APPDATA%）",
    ),
    "vlc": IsolationStrategy(
        app_id="vlc",
        exe_candidates=[
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        ],
        args_from_dir=_vlc_args,
        note="单实例转发经 --no-one-instance 绕过；--config 指定 per-clone vlcrc",
    ),
    "sumatrapdf": IsolationStrategy(
        app_id="sumatrapdf",
        exe_candidates=[
            r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
            r"%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe",
        ],
        args_from_dir=_sumatra_args,
        note="-appdata 收窄设置目录到 per-clone；-new-window 绕过既有窗口复用",
    ),
    "firefox": IsolationStrategy(
        app_id="firefox",
        exe_candidates=[
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
        args_from_dir=_firefox_args,
        note="remoting 单实例经 -no-remote 绕过；-profile 独立画像目录（经典全隔离）",
    ),
    "inkscape": IsolationStrategy(
        app_id="inkscape",
        exe_candidates=[
            r"C:\Program Files\Inkscape\bin\inkscape.exe",
            r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe",
        ],
        args_from_dir=_inkscape_args,
        env_from_dir=_inkscape_env,
        note="GApplication 单实例经 --app-id-tag 收窄到 per-clone；INKSCAPE_PROFILE_DIR 隔离偏好/扩展",
    ),
}

# 常见别名归一到注册表键。
_ALIASES = {
    "code": "vscode",
    "vs-code": "vscode",
    "vscode": "vscode",
    "devin": "devin-desktop",
    "windsurf": "devin-desktop",
    "devin-desktop": "devin-desktop",
    "google-chrome": "chrome",
    "msedge": "edge",
    "browser": "edge",
    "notepad++": "notepadpp",
    "npp": "notepadpp",
    "notepad-plus-plus": "notepadpp",
    "sumatra": "sumatrapdf",
}


def _resolve_app(app_id: str) -> str:
    key = (app_id or "").strip().lower()
    return _ALIASES.get(key, key)


def isolatable_apps() -> List[str]:
    """当前支持零配置分身隔离的软件键。"""
    return sorted(k for k, v in ISOLATION_REGISTRY.items() if v.isolatable)


def build_clone_launch(
    app_id: str,
    clone_id: str,
    root: str = DEFAULT_ROOT,
    extra_args: Optional[List[str]] = None,
) -> CloneLaunchSpec:
    """构造某分身内隔离启动某软件的规格。

    未登记的软件返回 isolatable=False + 空隔离参数（如实告知：只能裸启动，
    单实例软件仍会缠绕），绝不臆造隔离能力。
    """
    resolved = _resolve_app(app_id)
    data_dir = clone_data_root(clone_id, resolved, root)
    # 非标准安装路径经 DAO_CLONE_EXE_<APP>（如 DAO_CLONE_EXE_CHROME）显式指定，置于候选首位。
    override = os.environ.get("DAO_CLONE_EXE_" + re.sub(r"[^A-Za-z0-9]", "_", resolved).upper())
    strat = ISOLATION_REGISTRY.get(resolved)
    if strat is None:
        return CloneLaunchSpec(
            app_id=resolved,
            clone_id=_safe(clone_id),
            exe_candidates=[override] if override else [],
            args=list(extra_args or []),
            env={},
            data_dir=data_dir,
            isolatable=False,
            note="未登记隔离策略：裸启动；若该软件为 per-user 单实例则多分身仍会缠绕",
            pre_create=[data_dir],
        )
    args = list(strat.args_from_dir(data_dir))
    if extra_args:
        args.extend(extra_args)
    return CloneLaunchSpec(
        app_id=resolved,
        clone_id=_safe(clone_id),
        exe_candidates=([override] if override else []) + list(strat.exe_candidates),
        args=args,
        env=dict(strat.env_from_dir(data_dir)),
        data_dir=data_dir,
        isolatable=strat.isolatable,
        note=strat.note,
        pre_create=[data_dir] + list(strat.dirs_from_dir(data_dir)),
    )
