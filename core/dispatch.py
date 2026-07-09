"""通用适配层 · @ 调度内核（水善利万物而有静，道并行而不相悖）。

本源：把整台 Windows 做成一个"通用层"（layer=universal，默认落点），各专用软件
（KiCad/FreeCAD/嘉立创/HomeAssistant…）做成"领域工作层"（layer=domain），用 `@句柄`
唤起。Agent 拿到一句自然语言目标：

  · 显式 `@kicad 导出 gerber`  → 路由到 KiCad 工作层（领域专用动词）。
  · 无 @ 的普通目标           → 落在整机通用层（system），并跨层检索候选动词兜底。

领域工作层可以是本仓内置画像（origin=builtin），也可以是另一个 VS Code 子插件经 RPC
收编进来的外部画像（origin=external，见 core/subplugin.py）——对 Agent 而言两者一致，
皆通过统一的 @ 句柄唤起，实现"一个插件自动识别并调度所有子插件"的闭环。

纯逻辑、零第三方依赖，Linux/CI 即可单测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.profiles.registry import ProfileRegistry

# @句柄：@ 后跟字母/数字/._-（与账号名/扩展 id 片段一致），大小写不敏感。
_MENTION = re.compile(r"(?<![\w@])@([A-Za-z][A-Za-z0-9._-]*)")


@dataclass
class RouteDecision:
    """一次路由的裁决结果。"""

    # 命中的目标层 app_id 列表（有 @ 时=被唤起的领域层；无 @ 时=通用层）
    targets: list[str] = field(default_factory=list)
    # 落点层级："domain"（@ 唤起了专用层）/ "universal"（默认整机层）
    layer: str = "universal"
    # 文本里出现但当前未注册的句柄（子插件未安装/未就绪）——如实回报，不臆造
    unresolved: list[str] = field(default_factory=list)
    # 去掉 @句柄 后的净目标文本（供后续动词检索）
    clean_text: str = ""
    # 跨层动词候选（净文本检索所得），帮 Agent 收敛到具体动词
    verb_hints: list[dict] = field(default_factory=list)


class MentionRouter:
    """@ 调度器：解析 @句柄 → 裁定目标工作层 → 给出动词候选。"""

    def __init__(self, registry: ProfileRegistry) -> None:
        self.registry = registry

    # —— 句柄索引（handle → app_id），每次现算以吻合热加载/子插件动态注册 ——
    def _handle_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for app_id in self.registry.app_ids():
            prof = self.registry.get(app_id)
            if prof is None:
                continue
            index[prof.handle] = app_id
            # app_id 本身也可作句柄（mention 另设时仍兼容 @app_id）
            index.setdefault(app_id.lower(), app_id)
        return index

    def universal_app_ids(self) -> list[str]:
        return [a for a in self.registry.app_ids()
                if (p := self.registry.get(a)) is not None and p.is_universal]

    @staticmethod
    def parse_mentions(text: str) -> list[str]:
        """抽取文本中的 @句柄（保序去重，小写）。"""
        seen: list[str] = []
        for m in _MENTION.findall(text or ""):
            h = m.lower()
            if h not in seen:
                seen.append(h)
        return seen

    def route(self, text: str, verb_limit: int = 5) -> RouteDecision:
        """把一句自然语言目标裁定到通用层或被 @ 唤起的领域工作层。"""
        index = self._handle_index()
        mentions = self.parse_mentions(text)
        clean = _MENTION.sub("", text or "").strip()
        clean = re.sub(r"\s{2,}", " ", clean)

        targets: list[str] = []
        unresolved: list[str] = []
        for h in mentions:
            app_id = index.get(h)
            if app_id and app_id not in targets:
                targets.append(app_id)
            elif app_id is None:
                unresolved.append(h)

        if targets:
            layer = "domain"
        else:
            layer = "universal"
            targets = self.universal_app_ids()

        hints = self.registry.search_verbs(clean or text, limit=verb_limit) if (clean or text) else []
        # @ 唤起了专用层时，动词候选只保留目标层，避免跨层噪声。
        if layer == "domain":
            tset = set(targets)
            hints = [h for h in hints if h.get("app_id") in tset]
        return RouteDecision(
            targets=targets, layer=layer, unresolved=unresolved,
            clean_text=clean, verb_hints=hints,
        )

    def capability_manifest(self) -> dict:
        """统一能力清单：整机通用层 + 各 @句柄领域工作层，供 Agent 一览而择路。

        对 Agent 的语义：无 @ 即操作整台 Windows（universal）；需专门领域能力时
        @对应句柄 唤起工作层（domain）。builtin/external 一视同仁。
        """
        universal: list[dict] = []
        domains: list[dict] = []
        for app_id in self.registry.app_ids():
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
            "universal": universal,
            "domains": domains,
            "usage": "无 @ 的目标落在整机通用层；@<句柄> 唤起对应领域工作层（如 @kicad / @freecad）。",
        }
