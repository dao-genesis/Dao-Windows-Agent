"""整机 GUI 适配器：把整台 Windows 的可见桌面当作操作面（AI GUI 体系 pc_* 对等层）。

与级别②③（每 (session,app) 一张隔离桌面）不同，本层的操作面是**整机可见桌面本体**——
对标 devin-remote AI GUI 体系的 pc_* 词表（截屏/点/移/拖/滚/键/剪贴板/窗口/UI 树/变化侦测），
让 Agent 以"操作自己电脑"的对等方式操作整台 guest。语义优先铁律不变：凡有 target_hint
的动作先走 UIA 控件树，坐标只作最后手段且必须显式给出（不臆造）。

handler 返回结构化动作计划(dict)；运行期由注入的 executor（OsctlExecutor.run，实机绑
vendored agentctl）执行；未注入则 dry-run 返回计划本身，Linux/CI 可离线校验。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.adapter.base import ActionResult, AppAdapter, Instance
from core.profiles.schema import AutomationLevel

# 整机 GUI 动作原语（pc_* 对等）：operation 面为整机可见桌面，无需先 launch。
DESKTOP_OPS = (
    "windows",        # 枚举顶层窗口：{op} -> [{id,title,...}]
    "activate",       # 按标题子串激活窗口(并成为后续 find/tree 的作用域)：{op, title}
    "screenshot",     # 整机截屏落盘：{op, path?}
    "observe",        # 感知一帧(屏幕尺寸)：{op}
    "click_xy",       # 坐标点击(最后手段·须显式坐标)：{op, x, y, button?}
    "move_xy",        # 移动鼠标：{op, x, y}
    "drag_xy",        # 坐标拖拽：{op, x1, y1, x2, y2}
    "scroll",         # 滚轮：{op, dy?, dx?}
    "type_text",      # 焦点处输入 Unicode 文本：{op, text}
    "keys",           # 组合键/热键：{op, keys:"^s"}
    "clipboard_get",  # 读剪贴板：{op}
    "clipboard_set",  # 写剪贴板：{op, text}
    "find",           # 激活窗口作用域内按语义定位控件：{op, by, value, timeout?}
    "tree",           # 激活窗口作用域内导出 UIA 控件树：{op, depth?}
    "region_hash",    # 屏幕区域指纹：{op, x?, y?, w?, h?}
    "wait_change",    # 等区域出现变化：{op, x?, y?, w?, h?, timeout?}
    "locate",         # 语义优先定位(hint)：{op, target_hint}
    "click_hint",     # 语义优先点击(hint)：{op, target_hint}
    "type_hint",      # 语义优先输入(hint)：{op, target_hint, text}
)


class GuiDesktopAdapter(AppAdapter):
    level = AutomationLevel.VISION

    def __init__(self, profile, executor: Optional[Callable[[str, dict], Any]] = None):
        super().__init__(profile)
        self.executor = executor

    def launch(self, workdir: str, **kwargs: Any) -> Instance:
        meta = dict(kwargs)
        meta["desktop"] = ""  # 整机可见桌面本体，非隔离桌面
        return Instance(app_id=self.profile.app_id, workdir=workdir, meta=meta)

    def invoke(self, instance: Instance, verb: str, **params: Any) -> ActionResult:
        v = self.profile.verb(verb)
        if v is None:
            return ActionResult.bad(f"未知动词 '{verb}'，可用: {[x.name for x in self.profile.verbs]}")
        if v.handler is None:
            return ActionResult.bad(f"动词 '{verb}' 未绑定 handler")
        try:
            plan = v.handler(self, instance, **params)
        except Exception as exc:  # noqa: BLE001
            return ActionResult.bad(f"{type(exc).__name__}: {exc}")
        if self.executor is None:
            return ActionResult.good(
                {"dry_run": True, "desktop": "", "plan": plan},
                logs=["未绑定整机 GUI executor，返回待执行动作计划（离线校验）"],
            )
        res = self.executor("", plan)
        logs = [f"GUI on 整机桌面: {plan.get('verb', verb)}"]
        if isinstance(res, dict) and res.get("ok") is False:
            return ActionResult(ok=False, value=res,
                                error="整机 GUI 计划未全部命中(见 value.results)", logs=logs)
        return ActionResult.good(res, logs=logs)

    def shutdown(self, instance: Instance) -> None:
        instance.alive = False

    @staticmethod
    def build_plan(verb: str, steps: list[dict]) -> dict:
        for s in steps:
            op = s.get("op")
            if op not in DESKTOP_OPS:
                raise ValueError(f"非法整机 GUI op '{op}'，允许: {DESKTOP_OPS}")
        return {"verb": verb, "steps": steps}
