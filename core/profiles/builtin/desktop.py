"""整机 GUI 画像（AI GUI 体系收编 · pc_* 对等词表 · @gui 通用层）。

收编 devin-remote AI GUI 体系（inner-agent pc_* 15 词 + 语义 observe/find/act +
区域变化侦测）为本仓画像：与 `system`(@win · shell/文件) 互补——system 管无头控制面，
本画像管整机**可见桌面**的 GUI 面（截屏/鼠键/剪贴板/窗口/UIA 树/变化侦测）。

语义优先铁律：有 hint 的动作先走 UIA 控件树（click_hint/type_hint/locate/find/tree），
裸坐标动词(click/move/drag)是最后手段——调用方必须显式给坐标，绝不臆造。
"""
from __future__ import annotations

from core.adapter.gui_desktop import GuiDesktopAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb


def _observe(adapter, instance, **_):
    return adapter.build_plan("observe", [{"op": "windows"}, {"op": "observe"}])


def _screenshot(adapter, instance, path: str = "", **_):
    step = {"op": "screenshot"}
    if path:
        step["path"] = path
    return adapter.build_plan("screenshot", [step])


def _windows(adapter, instance, **_):
    return adapter.build_plan("windows", [{"op": "windows"}])


def _activate(adapter, instance, title: str, **_):
    return adapter.build_plan("activate", [{"op": "activate", "title": title}])


def _click(adapter, instance, x: int, y: int, button: str = "left", **_):
    return adapter.build_plan("click", [{"op": "click_xy", "x": x, "y": y, "button": button}])


def _move(adapter, instance, x: int, y: int, **_):
    return adapter.build_plan("move", [{"op": "move_xy", "x": x, "y": y}])


def _drag(adapter, instance, x1: int, y1: int, x2: int, y2: int, **_):
    return adapter.build_plan("drag", [
        {"op": "drag_xy", "x1": x1, "y1": y1, "x2": x2, "y2": y2},
    ])


def _scroll(adapter, instance, dy: int = 0, dx: int = 0, **_):
    return adapter.build_plan("scroll", [{"op": "scroll", "dy": dy, "dx": dx}])


def _type(adapter, instance, text: str, **_):
    return adapter.build_plan("type", [{"op": "type_text", "text": text}])


def _keys(adapter, instance, keys: str, **_):
    return adapter.build_plan("keys", [{"op": "keys", "keys": keys}])


def _clipboard_get(adapter, instance, **_):
    return adapter.build_plan("clipboard_get", [{"op": "clipboard_get"}])


def _clipboard_set(adapter, instance, text: str, **_):
    return adapter.build_plan("clipboard_set", [{"op": "clipboard_set", "text": text}])


def _ui_tree(adapter, instance, title: str, depth: int = 3,
             name: str = "", control_type: str = "", actionable_only: bool = False, **_):
    tree: dict = {"op": "tree", "depth": depth}
    if name:
        tree["name"] = name
    if control_type:
        tree["control_type"] = control_type
    if actionable_only:
        tree["actionable_only"] = True
    return adapter.build_plan("ui_tree", [
        {"op": "activate", "title": title},
        tree,
    ])


def _find(adapter, instance, title: str, name: str = "", control_type: str = "",
          timeout: int = 5, **_):
    spec: dict = {"op": "activate", "title": title}
    find: dict = {"op": "find", "timeout": timeout}
    if control_type:
        find.update({"by": "control_type", "value": control_type})
    else:
        find.update({"by": "name", "value": name})
    return adapter.build_plan("find", [spec, find])


def _click_hint(adapter, instance, hint: str, title: str = "", **_):
    steps: list[dict] = []
    if title:
        steps.append({"op": "activate", "title": title})
    steps.append({"op": "click_hint", "target_hint": hint})
    return adapter.build_plan("click_hint", steps)


def _type_hint(adapter, instance, hint: str, text: str, title: str = "", **_):
    steps: list[dict] = []
    if title:
        steps.append({"op": "activate", "title": title})
    steps.append({"op": "type_hint", "target_hint": hint, "text": text})
    return adapter.build_plan("type_hint", steps)


def _region_hash(adapter, instance, x: int = 0, y: int = 0, w: int = 0, h: int = 0, **_):
    step: dict = {"op": "region_hash", "x": x, "y": y}
    if w:
        step["w"] = w
    if h:
        step["h"] = h
    return adapter.build_plan("region_hash", [step])


def _wait_change(adapter, instance, x: int = 0, y: int = 0, w: int = 0, h: int = 0,
                 timeout: int = 10, **_):
    step: dict = {"op": "wait_change", "x": x, "y": y, "timeout": timeout}
    if w:
        step["w"] = w
    if h:
        step["h"] = h
    return adapter.build_plan("wait_change", [step])


def _where_changed(adapter, instance, x: int = 0, y: int = 0, w: int = 0, h: int = 0,
                   timeout: int = 10, **_):
    step: dict = {"op": "where_changed", "x": x, "y": y, "timeout": timeout}
    if w:
        step["w"] = w
    if h:
        step["h"] = h
    return adapter.build_plan("where_changed", [step])


PROFILE = AppProfile(
    app_id="desktop",
    display_name="整机 GUI (截屏/鼠键/剪贴板/窗口/UIA · AI GUI 体系收编)",
    level=AutomationLevel.VISION,
    launch={"attach_visible_desktop": True},
    file_conventions={"outputs": ["png"]},
    source_repo="devin-remote AI GUI 体系（inner-agent pc_* 词表收编·底座 core/gui/agentctl）",
    tags=("gui", "desktop", "pc", "整机", "收编"),
    layer="universal",
    mention="gui",
    prompt_snippet=(
        "整机 GUI 画像把整台 Windows 的可见桌面当作操作面（对等你操作自己电脑）："
        "观察(observe/screenshot/windows/ui_tree/region_hash/wait_change)、"
        "作用(activate/click/drag/scroll/type/keys/clipboard)。"
        "语义优先：能 click_hint/type_hint/find（UIA 控件树）绝不用裸坐标；"
        "裸坐标动词是最后手段且坐标必须来自实测（locate/find 的 rect），绝不臆造。"
    ),
    verbs=[
        Verb("observe", "感知一帧：顶层窗口列表+屏幕尺寸", handler=_observe, aliases=("look",)),
        Verb("screenshot", "整机截屏落盘(证据)", {"path": "保存路径(可选)"},
             handler=_screenshot, aliases=("shot", "capture")),
        Verb("windows", "枚举顶层窗口(id/标题)", handler=_windows, aliases=("list_windows",)),
        Verb("activate", "按标题子串激活窗口(成为 find/ui_tree 作用域)",
             {"title": "标题子串"}, handler=_activate, aliases=("focus",)),
        Verb("click", "坐标点击(最后手段·坐标须来自实测)",
             {"x": "横坐标", "y": "纵坐标", "button": "left|right"},
             handler=_click),
        Verb("move", "移动鼠标到坐标", {"x": "横坐标", "y": "纵坐标"}, handler=_move),
        Verb("drag", "坐标拖拽", {"x1": "起点x", "y1": "起点y", "x2": "终点x", "y2": "终点y"},
             handler=_drag),
        Verb("scroll", "滚轮滚动", {"dy": "纵向格数(负=下)", "dx": "横向格数"}, handler=_scroll),
        Verb("type", "焦点处输入 Unicode 文本", {"text": "文本"}, handler=_type,
             aliases=("type_text",)),
        Verb("keys", "组合键/热键(如 ctrl+s、alt+f4)", {"keys": "按键谱"}, handler=_keys,
             aliases=("hotkey", "key_combo")),
        Verb("clipboard_get", "读剪贴板文本", handler=_clipboard_get, aliases=("paste_read",)),
        Verb("clipboard_set", "写剪贴板文本", {"text": "文本"}, handler=_clipboard_set,
             aliases=("copy_write",)),
        Verb("ui_tree", "激活窗口并导出其 UIA 控件树(结构化之眼·归一 schema + 可按 name/类型过滤)",
             {"title": "窗口标题子串", "depth": "深度", "name": "按控件名过滤(子串·可选)",
              "control_type": "按控件类型过滤(如 Button·可选)",
              "actionable_only": "仅可交互控件(真=只留可点/可填·可选)"},
             handler=_ui_tree, aliases=("tree",)),
        Verb("find", "激活窗口并按语义定位控件(name 或 control_type)",
             {"title": "窗口标题子串", "name": "控件名", "control_type": "控件类型",
              "timeout": "秒"}, handler=_find),
        Verb("click_hint", "语义优先点击(UIA 命中→控件 rect；未命中如实报错)",
             {"hint": "目标描述", "title": "先激活的窗口标题(可选)"}, handler=_click_hint),
        Verb("type_hint", "语义优先输入(UIA set_value 优先)",
             {"hint": "目标描述", "text": "文本", "title": "先激活的窗口标题(可选)"},
             handler=_type_hint),
        Verb("region_hash", "屏幕区域指纹(sha256·变化侦测基线)",
             {"x": "左上x", "y": "左上y", "w": "宽", "h": "高"}, handler=_region_hash),
        Verb("wait_change", "等屏幕区域出现变化(轮询指纹)",
             {"x": "左上x", "y": "左上y", "w": "宽", "h": "高", "timeout": "秒"},
             handler=_wait_change),
        Verb("where_changed", "等区域变化并回变化位置(变化像素最小包围盒·绝对坐标)",
             {"x": "左上x", "y": "左上y", "w": "宽", "h": "高", "timeout": "秒"},
             handler=_where_changed),
    ],
)
_ADAPTER = GuiDesktopAdapter
