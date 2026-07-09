"""模式切换层（三插件融合的枢纽）：一个模式 = 提示词覆盖 + 工具面裁剪。

本源：Devin Desktop VSIX（编程基底）+ Proxy Pro（提示词隔离替换）+ 本仓 Windows
插件（整机桌面级路由与机控）三者融为一体后，Agent 不该被"一股脑全部工具"淹没——
用户按场景切换模式，底层随之替换提示词并裁剪工具面：

  · primary  主模式：帛书道德纪律 + 官方编程工具全集 + 整机操作为辅（日常默认）。
  · coding   纯编程：官方 Devin Desktop 原貌，整机机控面整体关闭。
  · windows  Windows 全接管：整机桌面级路由为主战场，官方编程提示词整体替换。
  · domain:<app_id>  专精领域：只保留该领域工作层 + 整机通用层（FreeCAD/KiCad/…）。

domain 模式不是硬编码清单，而是从 ProfileRegistry 的领域层画像现算——新增一个
领域 profile（或收编一个子插件）就自动多出一个专精模式（樸散則為器，框架不动）。

当前模式持久化为一份 JSON 契约文件（默认 ~/.dao/mode.json），供 Proxy Pro /
dao-desktop 等同装插件读取以联动替换各自的提示词与工具配置。纯标准库可单测。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from core.agent.rule import BASE_RULE, build_system_prompt
from core.profiles.registry import ProfileRegistry

# 工具面策略：all=全量（通用层+全部领域层）；none=整机机控面关闭；
# domain=仅指定领域层 + 通用层。
_POLICIES = ("all", "none", "domain")

DEFAULT_MODE = "primary"
DEFAULT_STATE_PATH = os.path.expanduser("~/.dao/mode.json")

_PRIMARY_OVERLAY = """【主模式】道德纪律为体，编程与整机操作为用。
官方 Devin Desktop 全部编程工具照常可用；整机机控面（桌面级路由 + 桥 /api/*）作为
辅助模块随时可调。日常开发以编程为主，涉及操作用户电脑时再落到机控面。"""

_CODING_OVERLAY = """【纯编程模式】官方 Devin Desktop 原貌：专注编程项目本身。
整机机控面已整体关闭——不调用桌面路由、不调用桥 /api/*，一切以代码与工程文件为准。"""

_WINDOWS_OVERLAY = """【Windows 全接管模式】整台 Windows 即你的主战场。
每个 IDE 窗口是一路隔离桌面会话（类虚拟机），你经桌面级路由所见即所得地操作真实
桌面，与用户真实桌面并行不悖。精确、可脚本化的操作优先走桥 /api/*（级别①），
仅当无 API 才降级 UIA/视觉。编程工具面退为辅助。"""

_DOMAIN_OVERLAY = """【专精模式 · {name}】当前专注 {name} 领域工作层。
工具面只保留 @{handle} 领域动词 + 整机通用层；先 describe_app 看领域纪律再 invoke。
领域工程完成后可切回主模式交接给其他环节。"""


@dataclass(frozen=True)
class Mode:
    """一个可切换的运行模式（提示词覆盖 + 工具面策略）。"""

    mode_id: str
    name: str
    summary: str
    prompt_overlay: str
    tool_policy: str = "all"            # all | none | domain
    domain_apps: tuple[str, ...] = ()   # tool_policy=domain 时保留的领域 app_id
    replace_official: bool = False      # 是否整体替换官方(编程)提示词面

    def describe(self) -> dict:
        return {
            "mode_id": self.mode_id,
            "name": self.name,
            "summary": self.summary,
            "tool_policy": self.tool_policy,
            "domain_apps": list(self.domain_apps),
            "replace_official": self.replace_official,
        }


class ModeManager:
    """模式登记 + 当前态持久化 + 模式感知的提示词/能力面组装。"""

    def __init__(
        self,
        registry: ProfileRegistry,
        state_path: str = DEFAULT_STATE_PATH,
    ) -> None:
        self.registry = registry
        self.state_path = state_path
        self._current = self._load_state() or DEFAULT_MODE

    # —— 模式清单（domain 模式从画像现算，吻合热加载/子插件动态收编）——
    def modes(self) -> list[Mode]:
        out = [
            Mode("primary", "主模式", "帛书纪律 + 编程全集 + 整机为辅（日常默认）",
                 _PRIMARY_OVERLAY, "all"),
            Mode("coding", "纯编程", "官方 Devin Desktop 原貌，机控面关闭",
                 _CODING_OVERLAY, "none"),
            Mode("windows", "Windows 全接管", "整机桌面级路由为主战场，编程面退辅",
                 _WINDOWS_OVERLAY, "all", replace_official=True),
        ]
        for app_id in self.registry.app_ids():
            prof = self.registry.get(app_id)
            if prof is None or prof.is_universal:
                continue
            out.append(Mode(
                f"domain:{prof.app_id}",
                f"专精 · {prof.display_name}",
                f"只保留 @{prof.handle} 领域工作层 + 整机通用层",
                _DOMAIN_OVERLAY.format(name=prof.display_name, handle=prof.handle),
                "domain",
                (prof.app_id,),
                replace_official=True,
            ))
        return out

    def get(self, mode_id: str) -> Mode | None:
        for m in self.modes():
            if m.mode_id == mode_id:
                return m
        return None

    # —— 当前态 ——
    @property
    def current(self) -> Mode:
        return self.get(self._current) or self.get(DEFAULT_MODE)  # type: ignore[return-value]

    def set(self, mode_id: str) -> Mode:
        mode = self.get(mode_id)
        if mode is None:
            known = [m.mode_id for m in self.modes()]
            raise ValueError(f"无此模式: {mode_id}（可用: {known}）")
        self._current = mode.mode_id
        self._save_state(mode)
        return mode

    # —— 工具面裁剪 ——
    def allowed_apps(self) -> list[str]:
        mode = self.current
        if mode.tool_policy == "none":
            return []
        if mode.tool_policy == "domain":
            keep = set(mode.domain_apps)
            out = []
            for app_id in self.registry.app_ids():
                prof = self.registry.get(app_id)
                if prof is None:
                    continue
                if prof.is_universal or prof.app_id in keep:
                    out.append(app_id)
            return out
        return self.registry.app_ids()

    def capabilities(self) -> dict:
        """模式感知的能力清单（在 @ 调度清单基础上按工具面策略裁剪）。"""
        mode = self.current
        allowed = set(self.allowed_apps())
        universal: list[dict] = []
        domains: list[dict] = []
        for app_id in self.registry.app_ids():
            if app_id not in allowed:
                continue
            prof = self.registry.get(app_id)
            if prof is None:
                continue
            entry = {
                "app_id": prof.app_id,
                "handle": "@" + prof.handle,
                "display_name": prof.display_name,
                "level": int(prof.level),
                "origin": prof.origin,
                "verbs": [v.name for v in prof.verbs],
            }
            (universal if prof.is_universal else domains).append(entry)
        return {
            "mode": mode.describe(),
            "universal": universal,
            "domains": domains,
        }

    def build_prompt(self, open_apps: list[str]) -> str:
        """模式感知的系统提示：模式覆盖 → 本源纪律 → 已开软件纪律 → 可调度模块清单。"""
        mode = self.current
        if mode.tool_policy == "none":
            return mode.prompt_overlay
        allowed = set(self.allowed_apps())
        base = build_system_prompt(self.registry, [a for a in open_apps if a in allowed])
        parts = [mode.prompt_overlay, "", base]
        if mode.tool_policy == "all":
            snippet = self.dispatch_snippet()
            if snippet:
                parts += ["", snippet]
        return "\n".join(parts)

    def dispatch_snippet(self) -> str:
        """通用调度层地基：告诉 Agent 有哪些领域模块可自主择用（@ 唤起或切专精模式）。

        终局形态里用户谈到某领域需求（3D 建模/PCB/智能家居…），Agent 应自主在整机
        桌面下打开对应软件并调用领域动词，工程完成后交接下一环节——本清单即其感知面。
        """
        lines: list[str] = []
        for app_id in self.registry.app_ids():
            prof = self.registry.get(app_id)
            if prof is None or prof.is_universal:
                continue
            tags = "·".join(prof.tags) if prof.tags else ""
            lines.append(f"- @{prof.handle} {prof.display_name}" + (f"（{tags}）" if tags else ""))
        if not lines:
            return ""
        return ("可自主调度的领域模块（用户需求触及某领域时，@ 句柄唤起该工作层，"
                "或建议切换到对应专精模式；工程完成后交接下一环节）：\n" + "\n".join(lines))

    # —— 契约文件（Proxy Pro / dao-desktop 联动读取）——
    def _load_state(self) -> str | None:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            mode_id = data.get("mode")
            return mode_id if isinstance(mode_id, str) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _save_state(self, mode: Mode) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "mode": mode.mode_id,
                        "name": mode.name,
                        "tool_policy": mode.tool_policy,
                        "replace_official": mode.replace_official,
                        "updated": int(time.time()),
                    },
                    f, ensure_ascii=False, indent=2,
                )
        except OSError:
            pass
