"""嘉立创EDA 画像（级别① · CDP 直驱 window._EXTAPI_ROOT_）。

收编自 Dao-PCB-Design-Agent 路线A（lceda_bridge/cdp_studio/eda_flow.py 等）。
经 CDP 在 pro.lceda.cn/editor 主页面上下文直接调用官方扩展 API（91 命名空间）。
handler 返回将在页面上下文执行的 JS 表达式（异步以 await 求值）。

要点（实测·PHASE4_FINDINGS）：编辑器页上下文里 dmt_Project.createProject 是**空操作**、
getAllProjectsUuid 只反映当前已打开工程——账号级工程 CRUD 必须走 REST 层（见 eda_rest.py），
不在本 CDP 画像内。
"""
from __future__ import annotations

from core.adapter.cdp import CdpEvalAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb

_ROOT = "window._EXTAPI_ROOT_"


def _api_namespaces(adapter, instance, **_):
    return f"Object.keys({_ROOT} || {{}})"


def _open_document(adapter, instance, uuid: str, **_):
    return f'{_ROOT}.dmt_EditorControl.openDocument({uuid!r})'


def _get_gerber(adapter, instance, name: str = "gerber", **_):
    return f'{_ROOT}.pcb_ManufactureData.getGerberFile({name!r})'


def _get_bom(adapter, instance, name: str = "bom", **_):
    return f'{_ROOT}.pcb_ManufactureData.getBomFile({name!r})'


def _get_pick_place(adapter, instance, name: str = "pickplace", **_):
    return f'{_ROOT}.pcb_ManufactureData.getPickAndPlaceFile({name!r})'


def _clear_routing(adapter, instance, scope: str = "all", **_):
    return f'{_ROOT}.pcb_Document.clearRouting({scope!r})'


def _rpc_call(adapter, instance, topic: str, payload: str = "{}", **_):
    return f'{_ROOT}.sys_MessageBus.rpcCall({topic!r}, {payload})'


PROFILE = AppProfile(
    app_id="jlceda",
    display_name="嘉立创EDA (在线 Web · CDP)",
    level=AutomationLevel.CDP,
    launch={"url": "https://pro.lceda.cn/editor", "via": "cdp", "api_root": _ROOT},
    file_conventions={"outputs": ["gerber", "bom", "pick_place", "pdf", "dsn"]},
    source_repo="Dao-PCB-Design-Agent (路线A: lceda_bridge/cdp_studio)",
    tags=("pcb", "eda", "web", "cdp"),
    prompt_snippet=(
        "嘉立创EDA 经 CDP 在编辑器页面上下文直接调 window._EXTAPI_ROOT_（91 官方 API 命名空间），"
        "无需安装扩展；每 session 独立 Chromium profile → 登录态与实例天然隔离。"
        "注意：dmt_Project.createProject 在编辑器页是空操作，账号级工程 CRUD 需走 REST 层。"
    ),
    verbs=[
        Verb("api_namespaces", "列出 _EXTAPI_ROOT_ 全部可用 API 命名空间", handler=_api_namespaces),
        Verb("open_document", "按 UUID 打开文档(pcb/sch)",
             {"uuid": "文档 UUID"}, handler=_open_document),
        Verb("export_gerber", "导出 Gerber 制造文件",
             {"name": "文件名"}, handler=_get_gerber, aliases=("gerber", "get_gerber")),
        Verb("export_bom", "导出 BOM", {"name": "文件名"}, handler=_get_bom, aliases=("bom",)),
        Verb("export_pick_place", "导出贴片坐标(Pick&Place)",
             {"name": "文件名"}, handler=_get_pick_place, aliases=("pick_place", "pos")),
        Verb("clear_routing", "清除布线", {"scope": "范围(all/...)"}, handler=_clear_routing),
        Verb("rpc_call", "经 sys_MessageBus 触达桌面核心 RPC",
             {"topic": "主题", "payload": "JSON 载荷"}, handler=_rpc_call),
    ],
)
_ADAPTER = CdpEvalAdapter
