"""嘉立创EDA 画像（级别① · CDP 直驱 window._EXTAPI_ROOT_）。

收编自 Dao-PCB-Design-Agent 路线A（lceda_bridge/cdp_studio）。
经 CDP 在 pro.lceda.cn/editor 主页面上下文直接调用官方扩展 API（91 命名空间）。
handler 返回将在页面上下文执行的 JS 表达式。
"""
from __future__ import annotations

from core.adapter.cdp import CdpEvalAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb

_ROOT = "window._EXTAPI_ROOT_"


def _api_namespaces(adapter, instance, **_):
    return f"Object.keys({_ROOT} || {{}})"


def _create_doc(adapter, instance, doc_type: str = "pcb", **_):
    return f"{_ROOT}.SYS_Document && {_ROOT}.SYS_Document.createNewDocument('{doc_type}')"


def _place_component(adapter, instance, lcsc: str, x: float = 0, y: float = 0, **_):
    return (f"{_ROOT}.PCB_Component && "
            f"{_ROOT}.PCB_Component.create({{lcsc:'{lcsc}', x:{x}, y:{y}}})")


def _export_gerber(adapter, instance, **_):
    return f"{_ROOT}.PCB_Manufacture && {_ROOT}.PCB_Manufacture.exportGerber()"


PROFILE = AppProfile(
    app_id="jlceda",
    display_name="嘉立创EDA (在线 Web · CDP)",
    level=AutomationLevel.CDP,
    launch={"url": "https://pro.lceda.cn/editor", "via": "cdp", "api_root": _ROOT},
    file_conventions={"outputs": ["gerber", "bom", "pick_place"]},
    source_repo="Dao-PCB-Design-Agent (路线A: lceda_bridge/cdp_studio)",
    tags=("pcb", "eda", "web", "cdp"),
    prompt_snippet=(
        "嘉立创EDA 经 CDP 在编辑器页面上下文直接调 window._EXTAPI_ROOT_（91 官方 API 命名空间），"
        "无需安装扩展。每个 session 用独立 Chromium profile → 登录态与实例天然隔离。"
    ),
    verbs=[
        Verb("api_namespaces", "列出 _EXTAPI_ROOT_ 全部可用 API 命名空间", handler=_api_namespaces),
        Verb("create_doc", "新建文档(pcb/sch/...)", {"doc_type": "文档类型"}, handler=_create_doc),
        Verb("place_component", "按 LCSC 编号放置元件",
             {"lcsc": "立创商城编号", "x": "X", "y": "Y"}, handler=_place_component),
        Verb("export_gerber", "导出 Gerber 制造文件", handler=_export_gerber, aliases=("gerber",)),
    ],
)
_ADAPTER = CdpEvalAdapter
