"""级别② 桌面 UIA 适配器：隔离桌面 + UIAutomation 控件级驱动（GUI-only 软件兜底）。

三级回退铁律：能走级别①(API/CLI/CDP) 绝不上级别②。只有软件**没有**可脚本入口时，
才落到这一层——在**独立桌面**(Win32 CreateDesktop) 上起进程，经 UIAutomation 按
控件（name/automationId/control_type）而非坐标操作 → 与用户主桌面互不干扰、天然隔离并行。

设计对齐 CdpEvalAdapter：handler 返回一份**结构化 UIA 动作计划**(纯 dict，可 JSON 化)，
运行期由注入的 driver（guest 内 pywinauto/comtypes 实现，见 coldstart）执行；未注入 driver
时进入 dry-run，返回该计划本身，便于在 Linux 上离线校验（无需真机/GUI）。

driver 契约：Callable[[str, dict], Any]
    driver(desktop, plan) -> 执行结果；desktop 为隔离桌面名，plan 见 build_plan。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.adapter.base import ActionResult, AppAdapter, Instance
from core.profiles.schema import AutomationLevel

# UIA 动作原语：driver 须实现下列 op，均按控件定位（绝不用绝对坐标）。
UIA_OPS = (
    "launch",       # 在隔离桌面起进程：{op, exe, args?, match_class?(打包应用逃逸兜底)}
    "find",         # 定位控件：{op, by:name|automation_id|control_type, value, timeout?}
    "click",        # 点击已定位控件：{op, target}
    "set_value",    # 写入文本框：{op, target, text}
    "get_text",     # 读控件文本：{op, target}
    "invoke",       # 触发默认动作(按钮等)：{op, target}
    "menu",         # 走菜单路径：{op, path:["文件","另存为"]}
    "keys",         # 发送按键(控件焦点内)：{op, keys:"^s"}
    "tree",         # 导出控件树(感知)：{op, depth?}
    "screenshot",   # 隔离桌面截图(级别③兜底前的证据)：{op}
)


def desktop_name(app_id: str, session_id: str) -> str:
    """每 (session, app) 一张独立桌面 → N 实例并行互不串扰。"""
    return f"dao_{session_id}_{app_id}"


class UiaDesktopAdapter(AppAdapter):
    level = AutomationLevel.UIA_DESKTOP

    def __init__(self, profile, driver: Optional[Callable[[str, dict], Any]] = None):
        super().__init__(profile)
        self.driver = driver

    def launch(self, workdir: str, **kwargs: Any) -> Instance:
        session_id = str(kwargs.get("session_id", "vm"))
        desk = desktop_name(self.profile.app_id, session_id)
        meta = dict(kwargs)
        meta["desktop"] = desk
        return Instance(app_id=self.profile.app_id, workdir=workdir, meta=meta)

    def invoke(self, instance: Instance, verb: str, **params: Any) -> ActionResult:
        v = self.profile.verb(verb)
        if v is None:
            return ActionResult.bad(f"未知动词 '{verb}'，可用: {[x.name for x in self.profile.verbs]}")
        if v.handler is None:
            return ActionResult.bad(f"动词 '{verb}' 未绑定 handler")
        try:
            plan = v.handler(self, instance, **params)  # handler 返回 UIA 动作计划(dict)
        except Exception as exc:  # noqa: BLE001
            return ActionResult.bad(f"{type(exc).__name__}: {exc}")
        desk = instance.meta.get("desktop", "")
        if self.driver is None:
            return ActionResult.good(
                {"dry_run": True, "desktop": desk, "plan": plan},
                logs=["未绑定 UIA driver，返回待执行动作计划（离线校验）"],
            )
        return ActionResult.good(self.driver(desk, plan),
                                 logs=[f"UIA on {desk}: {plan.get('verb', verb)}"])

    def shutdown(self, instance: Instance) -> None:
        instance.alive = False

    # --- 供 handler 复用：拼装一份规范的动作计划 ---
    @staticmethod
    def build_plan(verb: str, steps: list[dict]) -> dict:
        for s in steps:
            op = s.get("op")
            if op not in UIA_OPS:
                raise ValueError(f"非法 UIA op '{op}'，允许: {UIA_OPS}")
        return {"verb": verb, "steps": steps}
