"""应用适配器基类与执行结果。

适配器把一个 profile 的抽象动词，落到具体驱动面（API/CLI/CDP/UIA/Vision）上。
级别① 适配器在 Linux/Windows 均可无头运行，天然隔离并行。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional

from core.profiles.schema import AppProfile, AutomationLevel


@dataclass
class ActionResult:
    ok: bool
    value: Any = None
    error: str = ""
    logs: list[str] = field(default_factory=list)

    @classmethod
    def good(cls, value: Any = None, logs: Optional[list[str]] = None) -> "ActionResult":
        return cls(ok=True, value=value, logs=logs or [])

    @classmethod
    def bad(cls, error: str, logs: Optional[list[str]] = None) -> "ActionResult":
        return cls(ok=False, error=error, logs=logs or [])


@dataclass
class Instance:
    """一个已启动/附着的软件实例（属于某个 session）。"""

    app_id: str
    handle: Any = None            # 子进程 / CDP target / 窗口句柄
    workdir: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    alive: bool = True


class AppAdapter(abc.ABC):
    """软件适配器接口。一个 profile 绑定一个 adapter。"""

    level: AutomationLevel

    def __init__(self, profile: AppProfile):
        self.profile = profile

    @abc.abstractmethod
    def launch(self, workdir: str, **kwargs: Any) -> Instance:
        """在隔离会话内启动/附着软件，返回实例句柄。"""

    @abc.abstractmethod
    def invoke(self, instance: Instance, verb: str, **params: Any) -> ActionResult:
        """执行一个高层动词。"""

    @abc.abstractmethod
    def shutdown(self, instance: Instance) -> None:
        """销毁实例，释放资源。"""

    def health(self, instance: Instance) -> bool:
        return instance.alive
