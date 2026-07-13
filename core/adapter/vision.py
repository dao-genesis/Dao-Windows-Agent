"""级别③ 视觉 grounding 适配器：隔离桌面截图 + 视觉定位（无 UIA 时的最后兜底）。

三级回退铁律的**末级**：仅当软件既无脚本入口(①)、UIA 又抓不到有效控件(②)时才落到这里。
本级不按控件、而按"截图 + 自然语言目标描述 → grounding 模型给出坐标 → 在隔离桌面点击/输入"。
坐标是**最后手段**，故本级动词一律显式声明 `target_hint`（要点/找什么），把可解释性留在计划里。

对齐 UiaDesktopAdapter：handler 返回结构化视觉动作计划(dict)；运行期由注入的 grounder
执行（guest 内接 grounding 模型/OCR），未注入则 dry-run 返回计划本身，Linux 上可离线单测。

grounder 契约：Callable[[str, dict], Any]  grounder(desktop, plan) -> 结果。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.adapter.base import ActionResult, AppAdapter, Instance
from core.adapter.uia_desktop import desktop_name
from core.profiles.schema import AutomationLevel

# 视觉动作原语：全部以"截图 + 目标描述"为中心，坐标由 grounder 现场求解。
VISION_OPS = (
    "launch",        # 隔离桌面起进程：{op, exe, args?}
    "observe",       # 截图 + 可选 OCR/元素检测：{op}
    "locate",        # 按自然语言目标定位：{op, target_hint} -> 归一化坐标
    "click_hint",    # 定位并点击：{op, target_hint, button?}
    "type_hint",     # 定位输入框并输入：{op, target_hint, text}
    "drag_hint",     # 从 A 拖到 B：{op, from_hint, to_hint}
    "wait_for",      # 等到目标出现：{op, target_hint, timeout?}
    "assert_visible",# 断言目标可见（验收）：{op, target_hint}
)


class VisionAdapter(AppAdapter):
    level = AutomationLevel.VISION

    def __init__(self, profile, grounder: Optional[Callable[[str, dict], Any]] = None):
        super().__init__(profile)
        self.grounder = grounder

    def launch(self, workdir: str, **kwargs: Any) -> Instance:
        session_id = str(kwargs.get("session_id", "vm"))
        meta = dict(kwargs)
        meta["desktop"] = desktop_name(self.profile.app_id, session_id)
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
        desk = instance.meta.get("desktop", "")
        if self.grounder is None:
            return ActionResult.good(
                {"dry_run": True, "desktop": desk, "plan": plan},
                logs=["未绑定 vision grounder，返回待执行视觉计划（离线校验）"],
            )
        res = self.grounder(desk, plan)
        logs = [f"VISION on {desk}: {plan.get('verb', verb)}"]
        if isinstance(res, dict) and res.get("ok") is False:
            return ActionResult(ok=False, value=res,
                                error="视觉计划未全部命中(见 value.results)", logs=logs)
        return ActionResult.good(res, logs=logs)

    def shutdown(self, instance: Instance) -> None:
        instance.alive = False

    @staticmethod
    def build_plan(verb: str, steps: list[dict]) -> dict:
        for s in steps:
            op = s.get("op")
            if op not in VISION_OPS:
                raise ValueError(f"非法 vision op '{op}'，允许: {VISION_OPS}")
        return {"verb": verb, "steps": steps}
