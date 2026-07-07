"""帛书 · agent 提示词纪律（从 ha-copilot AGENT_RULE 泛化到"任意软件"）。

组装给 AI 的系统提示：本源纪律 + 当前会话内已打开软件的 profile.prompt_snippet。
"""
from __future__ import annotations

from core.profiles.registry import ProfileRegistry

BASE_RULE = """你是这套超级插件的核心 Agent。每个 IDE 窗口是一个隔离会话（类虚拟机），
你在其中全权操作用户电脑一切资源，且与用户真实桌面互不干扰。

本源纪律：
1. 先 search_verbs 找能力、describe_app 看细节，再 invoke——不臆测动词名。
2. 优先级别①（软件原生 API/CLI/CDP，无头·天然隔离）；仅当软件无 API 才降级到隔离桌面 UIA/视觉。
3. 文件极简：工程文件即真源，改参重放优于重建（反者道之动）。
4. 出错先读回显与 logs 自愈，再重试；不确定就少做，宁缺毋滥（大成若缺）。
无为而无不为 · 道法自然。"""


def build_system_prompt(registry: ProfileRegistry, open_apps: list[str]) -> str:
    parts = [BASE_RULE, "", "当前会话已接入软件："]
    if not open_apps:
        parts.append("（无。用 open_app 打开需要的软件）")
    for app_id in open_apps:
        prof = registry.get(app_id)
        if prof is None:
            continue
        verbs = ", ".join(v.name for v in prof.verbs)
        parts.append(f"- {prof.display_name} [{app_id}] 级别{int(prof.level)}: {verbs}")
        if prof.prompt_snippet:
            parts.append(f"  纪律: {prof.prompt_snippet}")
    return "\n".join(parts)
