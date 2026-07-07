"""级别① 通用无头适配器：经 CLI / 脚本 API 驱动软件。

适用于任何提供命令行或可脚本化入口的软件（FreeCADCmd、kicad-cli、pcbnew Python…）。
动词的 handler 直接在此适配器上下文中被调用，可复用各仓库现有驱动函数。
"""
from __future__ import annotations

import os
import subprocess
from typing import Any

from core.adapter.base import ActionResult, AppAdapter, Instance
from core.profiles.schema import AutomationLevel


class SubprocessApiAdapter(AppAdapter):
    """经子进程/CLI 驱动的无头适配器（天然隔离·可并行·不上可见桌面）。"""

    level = AutomationLevel.API

    def launch(self, workdir: str, **kwargs: Any) -> Instance:
        os.makedirs(workdir, exist_ok=True)
        return Instance(app_id=self.profile.app_id, workdir=workdir, meta=dict(kwargs))

    def invoke(self, instance: Instance, verb: str, **params: Any) -> ActionResult:
        v = self.profile.verb(verb)
        if v is None:
            return ActionResult.bad(f"未知动词 '{verb}'，可用: {[x.name for x in self.profile.verbs]}")
        if v.handler is None:
            return ActionResult.bad(f"动词 '{verb}' 未绑定 handler（仅声明）")
        try:
            value = v.handler(self, instance, **params)
            if isinstance(value, ActionResult):
                return value
            return ActionResult.good(value)
        except Exception as exc:  # noqa: BLE001 - 适配器边界统一兜底
            return ActionResult.bad(f"{type(exc).__name__}: {exc}")

    def shutdown(self, instance: Instance) -> None:
        instance.alive = False

    # --- 供 handler 复用的底层能力 ---
    def run_cli(self, args: list[str], instance: Instance, timeout: int = 120) -> ActionResult:
        """在实例工作目录内执行 CLI，捕获输出。"""
        try:
            proc = subprocess.run(
                args,
                cwd=instance.workdir or None,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return ActionResult.bad(f"可执行文件不存在: {args[0]}（Windows 冷启动/真机才装）")
        except subprocess.TimeoutExpired:
            return ActionResult.bad(f"CLI 超时(>{timeout}s): {' '.join(args)}")
        logs = [f"$ {' '.join(args)}"]
        if proc.stdout:
            logs.append(proc.stdout.strip())
        if proc.returncode != 0:
            return ActionResult.bad(proc.stderr.strip() or f"退出码 {proc.returncode}", logs)
        return ActionResult.good({"stdout": proc.stdout, "returncode": proc.returncode}, logs)
