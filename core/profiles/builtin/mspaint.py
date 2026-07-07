"""画图画像（级别③ · 隔离桌面 + 视觉 grounding · Level③ 验证标靶）。

画图(mspaint) 的画布是一整块自绘位图，UIA 抓不到任何有意义的子控件——正是级别③ 的典型场景：
既无脚本 API(①)、UIA 也无解(②)，只能"截图 + 视觉定位 + 坐标操作"兜底。本画像作为级别③ 标靶。
任何"画布类/自绘 UI"软件的接入模式与此同构。
"""
from __future__ import annotations

from core.adapter.vision import VisionAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb


def _open(adapter, instance, **_):
    return adapter.build_plan("open", [
        {"op": "launch", "exe": "mspaint.exe"},
        {"op": "wait_for", "target_hint": "画图窗口的画布区域", "timeout": 10},
    ])


def _pick_tool(adapter, instance, tool: str, **_):
    return adapter.build_plan("pick_tool", [
        {"op": "observe"},
        {"op": "click_hint", "target_hint": f"工具栏中的“{tool}”工具按钮"},
    ])


def _stroke(adapter, instance, frm: str = "画布左上", to: str = "画布右下", **_):
    return adapter.build_plan("stroke", [
        {"op": "drag_hint", "from_hint": frm, "to_hint": to},
    ])


def _observe(adapter, instance, **_):
    return adapter.build_plan("observe", [{"op": "observe"}])


def _assert(adapter, instance, target_hint: str, **_):
    return adapter.build_plan("assert_visible", [
        {"op": "assert_visible", "target_hint": target_hint},
    ])


PROFILE = AppProfile(
    app_id="mspaint",
    display_name="画图 (Paint · 级别③标靶)",
    level=AutomationLevel.VISION,
    launch={"exe": "mspaint.exe", "isolated_desktop": True},
    window_match={"class_name": "MSPaintApp"},
    file_conventions={"outputs": ["png", "bmp"]},
    source_repo="本仓（级别③ 验证标靶）",
    tags=("gui", "vision", "level3", "标靶"),
    prompt_snippet=(
        "画图走级别③：截图 + 视觉 grounding（无 UIA 兜底）。坐标是最后手段——"
        "每步都以自然语言目标描述(target_hint) 定位，保留可解释性。仅在①②皆不可用时才用本级。"
    ),
    verbs=[
        Verb("open", "在隔离桌面启动画图并等画布就绪", handler=_open, aliases=("launch",)),
        Verb("pick_tool", "视觉定位并选择工具栏工具",
             {"tool": "工具名，如 铅笔/刷子/填充"}, handler=_pick_tool, aliases=("tool",)),
        Verb("stroke", "在画布上拖拽画一笔",
             {"frm": "起点描述", "to": "终点描述"}, handler=_stroke, aliases=("draw",)),
        Verb("observe", "截图+观察当前画面(感知)", handler=_observe, aliases=("screenshot",)),
        Verb("assert_visible", "断言某目标在画面中可见(验收)",
             {"target_hint": "要确认可见的目标描述"}, handler=_assert, aliases=("assert",)),
    ],
)
_ADAPTER = VisionAdapter
