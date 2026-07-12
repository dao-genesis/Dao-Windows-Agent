"""子插件发现（樸散為器 · 道并行而不相悖）。

约定：每个 DAO 子插件（另一个 VS Code 扩展，如 FreeCAD/KiCad 专用扩展）在发现目录
落一个描述符 JSON（默认 ~/.dao/subplugins/*.json），声明自身 app_id / @句柄 / 领域动词
及一个本地 invoke 端点。主插件启动时扫描此目录，把每个子插件收编为一个 external 画像，
其动词经 RemoteSubpluginAdapter RPC 代理——从此 Agent 用统一 @ 句柄即可调度它们，
无需改框架，用户装了哪个子插件就自动多出哪一路领域工作层。

描述符 schema（最小集）：
    {
      "app_id": "freecad-ext",          # 唯一 id（建议带 -ext 以别于内置画像）
      "display_name": "FreeCAD (3D·子插件)",
      "mention": "freecad",             # @ 句柄；省略退回 app_id
      "layer": "domain",                # 领域工作层（几乎恒为 domain）
      "level": 1,                        # 驱动级别 1/2/3
      "source": "vscode:dao-agi.freecad",
      "invoke_url": "http://127.0.0.1:18920/invoke",
      "token": "可选",
      "prompt_snippet": "领域纪律…",
      "verbs": [
        {"name": "export_step", "summary": "导出 STEP",
         "params": {"doc": "工程路径"}, "aliases": ["step"]}
      ]
    }

纯 stdlib，transport 可注入（默认 urllib）以便单测。
"""
from __future__ import annotations

import json
import os
from typing import Callable, Optional

from core.adapter.remote import RemoteSubpluginAdapter, Transport
from core.profiles.registry import ProfileRegistry
from core.profiles.schema import AppProfile, AutomationLevel, Verb


def default_discovery_dir() -> str:
    return os.environ.get("DAO_SUBPLUGIN_DIR") or os.path.join(
        os.path.expanduser("~"), ".dao", "subplugins")


def _level(raw: object) -> AutomationLevel:
    try:
        return AutomationLevel(int(raw))  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return AutomationLevel.API


def profile_from_descriptor(desc: dict) -> AppProfile:
    """把一个子插件描述符构建成 external 画像（动词 handler 由适配器 RPC 兜底，不内联）。"""
    app_id = str(desc.get("app_id") or "").strip()
    if not app_id:
        raise ValueError("子插件描述符缺 app_id")
    verbs: list[Verb] = []
    for v in desc.get("verbs") or []:
        if isinstance(v, str):
            v = {"name": v}
        elif not isinstance(v, dict):
            continue
        name = str(v.get("name") or "").strip()
        if not name:
            continue
        verbs.append(Verb(
            name=name,
            summary=str(v.get("summary") or ""),
            params={str(k): str(val) for k, val in (v.get("params") or {}).items()},
            aliases=tuple(str(a) for a in (v.get("aliases") or [])),
        ))
    if not verbs:
        raise ValueError(f"[{app_id}] 子插件至少要声明一个 verb")
    return AppProfile(
        app_id=app_id,
        display_name=str(desc.get("display_name") or app_id),
        level=_level(desc.get("level")),
        source_repo=str(desc.get("source") or "external subplugin"),
        tags=tuple(str(t) for t in (desc.get("tags") or ("external",))),
        layer=str(desc.get("layer") or "domain"),
        mention=str(desc.get("mention") or ""),
        origin="external",
        prompt_snippet=str(desc.get("prompt_snippet") or ""),
        verbs=verbs,
    )


def load_descriptors(discovery_dir: Optional[str] = None) -> list[dict]:
    """读发现目录下全部 *.json 描述符（损坏的跳过，不炸整体）。"""
    d = discovery_dir or default_discovery_dir()
    out: list[dict] = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                desc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(desc, dict):
            desc.setdefault("_file", name)
            out.append(desc)
    return out


def register_subplugins(registry: ProfileRegistry,
                        discovery_dir: Optional[str] = None,
                        transport: Optional[Transport] = None) -> list[str]:
    """扫描发现目录，把子插件收编进 registry。返回成功收编的 app_id 列表。

    与既有 app_id 冲突者跳过（内置画像优先，避免子插件劫持整机通用层等）。
    """
    registered: list[str] = []
    existing = set(registry.app_ids())
    for desc in load_descriptors(discovery_dir):
        try:
            prof = profile_from_descriptor(desc)
        except Exception:  # 描述符坏的跳过，不炸整体
            continue
        if prof.app_id in existing:
            continue
        invoke_url = str(desc.get("invoke_url") or "").strip()
        if not invoke_url:
            continue
        token = str(desc.get("token") or "")
        registry.register(
            prof,
            (lambda p, u=invoke_url, t=token: RemoteSubpluginAdapter(
                p, invoke_url=u, token=t, transport=transport)),
        )
        existing.add(prof.app_id)
        registered.append(prof.app_id)
    return registered
