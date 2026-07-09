"""应用画像 (App Profile) schema。

一个 profile = 一个软件接入本体系需要声明的全部信息（薄片，软编码）。
新增软件 = 写一个 profile，框架不动。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class AutomationLevel(enum.IntEnum):
    """驱动级别（数字越小越优先/越底层稳定）。"""

    API = 1        # 原生脚本/插件 API、CLI、本地 IPC（无头，天然隔离并行）
    CDP = 1        # Web 应用经 Chrome DevTools Protocol 直驱（等价 API 级）
    UIA_DESKTOP = 2  # 隔离桌面 + UIAutomation 控件级（GUI-only 软件）
    VISION = 3     # 隔离桌面 + 视觉 grounding（无 UIA 兜底）


@dataclass(frozen=True)
class Verb:
    """一个高层动词：AI/agent 可调用的软件能力单元。

    handler 收到 (session, **params) 返回任意可序列化结果。
    """

    name: str
    summary: str
    params: dict[str, str] = field(default_factory=dict)  # name -> 说明
    handler: Optional[Callable[..., Any]] = None
    aliases: tuple[str, ...] = ()

    def search_text(self) -> str:
        return " ".join([self.name, self.summary, *self.aliases, *self.params.keys()])


@dataclass
class AppProfile:
    """软件画像。"""

    app_id: str                     # 唯一标识，如 "kicad" / "freecad" / "jlceda"
    display_name: str
    level: AutomationLevel
    # 启动/附着：Linux 上多为 headless CLI；Windows 上可为独立桌面进程
    launch: dict[str, Any] = field(default_factory=dict)
    # 窗口/进程匹配（级别②③ 用）
    window_match: dict[str, Any] = field(default_factory=dict)
    # 文件约定（工程/导出格式）
    file_conventions: dict[str, Any] = field(default_factory=dict)
    # 高层动词表
    verbs: list[Verb] = field(default_factory=list)
    # 注入 agent 的提示词片段（帛书·领域纪律）
    prompt_snippet: str = ""
    # 来源仓库（可复用资产追溯）
    source_repo: str = ""
    tags: tuple[str, ...] = ()
    # —— 通用适配层字段（樸散為器：整机通用层 vs 领域专用层，@ 调度）——
    # layer："universal"=整台 Windows 通用层（默认落点）；"domain"=专用软件工作层（需 @ 唤起）
    layer: str = "domain"
    # mention：@ 唤起句柄；为空时退回 app_id。如 @win 唤起整机、@kicad 唤起 PCB 工作层
    mention: str = ""
    # origin："builtin"=内置画像；"external"=外部子插件（另一 VS Code 扩展）经 RPC 收编
    origin: str = "builtin"

    @property
    def handle(self) -> str:
        """@ 调度句柄（去掉前导 @，小写）——为空退回 app_id。"""
        return (self.mention or self.app_id).lstrip("@").lower()

    @property
    def is_universal(self) -> bool:
        return self.layer == "universal"

    def verb(self, name: str) -> Optional[Verb]:
        for v in self.verbs:
            if v.name == name or name in v.aliases:
                return v
        return None

    def validate(self) -> list[str]:
        errs: list[str] = []
        if not self.app_id:
            errs.append("app_id 不能为空")
        if not self.verbs:
            errs.append(f"[{self.app_id}] 至少要声明一个 verb")
        seen: set[str] = set()
        for v in self.verbs:
            for key in (v.name, *v.aliases):
                if key in seen:
                    errs.append(f"[{self.app_id}] 动词名冲突: {key}")
                seen.add(key)
        return errs
