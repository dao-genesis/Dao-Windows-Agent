"""记事本画像（级别② · 隔离桌面 + UIA 控件级 · Level② 验证标靶）。

Notepad 是 Windows 自带、无任何脚本 API 的 GUI-only 软件——正是级别② 的典型场景。
本画像用作级别② 全链路的**验证标靶**：在隔离桌面(CreateDesktop)上起 notepad.exe，
经 UIAutomation 写入/读回文本、走菜单另存为——全程不上用户主桌面、可 N 份并行。
"""
from __future__ import annotations

from core.adapter.uia_desktop import UiaDesktopAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb

_EDIT = {"by": "control_type", "value": "Edit"}


def _open(adapter, instance, file: str = "", **_):
    args = [file] if file else []
    return adapter.build_plan("open", [
        {"op": "launch", "exe": "notepad.exe", "args": args, "match_class": "Notepad"},
        {"op": "find", **_EDIT, "timeout": 10},
    ])


def _type_text(adapter, instance, text: str, **_):
    return adapter.build_plan("type_text", [
        {"op": "find", **_EDIT},
        {"op": "set_value", "target": _EDIT, "text": text},
    ])


def _read_text(adapter, instance, **_):
    return adapter.build_plan("read_text", [
        {"op": "find", **_EDIT},
        {"op": "get_text", "target": _EDIT},
    ])


def _save_as(adapter, instance, path: str, **_):
    return adapter.build_plan("save_as", [
        {"op": "keys", "keys": "^+s"},
        {"op": "find", "by": "name", "value": "文件名:", "timeout": 5},
        {"op": "set_value", "target": {"by": "name", "value": "文件名:"}, "text": path},
        {"op": "keys", "keys": "{ENTER}"},
    ])


def _controls_tree(adapter, instance, depth: int = 3, **_):
    return adapter.build_plan("controls_tree", [{"op": "tree", "depth": depth}])


def _screenshot(adapter, instance, **_):
    return adapter.build_plan("screenshot", [{"op": "screenshot"}])


PROFILE = AppProfile(
    app_id="notepad",
    display_name="记事本 (Notepad · 级别②标靶)",
    level=AutomationLevel.UIA_DESKTOP,
    launch={"exe": "notepad.exe", "isolated_desktop": True},
    window_match={"class_name": "Notepad", "control_type": "Window"},
    file_conventions={"outputs": ["txt"]},
    source_repo="本仓（级别② 验证标靶）",
    tags=("gui", "uia", "level2", "标靶"),
    prompt_snippet=(
        "记事本走级别②：隔离桌面 + UIA 控件级（按 control_type/name 定位，绝不用坐标）。"
        "它是级别② 链路的验证标靶——任何 GUI-only 软件的接入模式与此同构。"
    ),
    verbs=[
        Verb("open", "在隔离桌面启动记事本（可带文件路径）",
             {"file": "可选·要打开的 .txt"}, handler=_open, aliases=("launch",)),
        Verb("type_text", "向编辑区写入文本(UIA set_value)",
             {"text": "要写入的文本"}, handler=_type_text, aliases=("write",)),
        Verb("read_text", "读回编辑区文本(UIA get_text)", handler=_read_text, aliases=("read",)),
        Verb("save_as", "另存为指定路径(菜单+文件对话框)",
             {"path": "保存路径"}, handler=_save_as, aliases=("save",)),
        Verb("controls_tree", "导出当前窗口 UIA 控件树(感知)",
             {"depth": "深度"}, handler=_controls_tree, aliases=("tree",)),
        Verb("screenshot", "隔离桌面截图(证据/级别③兜底入口)", handler=_screenshot),
    ],
)
_ADAPTER = UiaDesktopAdapter
