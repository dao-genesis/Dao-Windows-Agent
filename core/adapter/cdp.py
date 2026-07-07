"""级别① Web 应用适配器：经 Chrome DevTools Protocol 直驱页面内官方 API。

对标 Dao-PCB-Design-Agent 路线A（嘉立创EDA）：在 pro.lceda.cn/editor 页面上下文
直接调用挂在 window._EXTAPI_ROOT_ 的 91 个官方 API 命名空间——无需安装扩展/沙箱。

evaluator: Callable[[str], Any] 由运行期注入（可接 DAO Bridge browser_eval /
本地 Playwright CDP）。未注入时进入 dry-run，返回将要执行的 JS 表达式，便于离线校验。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.adapter.base import ActionResult, AppAdapter, Instance
from core.profiles.schema import AutomationLevel


class CdpEvalAdapter(AppAdapter):
    level = AutomationLevel.CDP

    def __init__(self, profile, evaluator: Optional[Callable[[str], Any]] = None):
        super().__init__(profile)
        self.evaluator = evaluator

    def launch(self, workdir: str, **kwargs: Any) -> Instance:
        return Instance(app_id=self.profile.app_id, workdir=workdir, meta=dict(kwargs))

    def invoke(self, instance: Instance, verb: str, **params: Any) -> ActionResult:
        v = self.profile.verb(verb)
        if v is None:
            return ActionResult.bad(f"未知动词 '{verb}'，可用: {[x.name for x in self.profile.verbs]}")
        if v.handler is None:
            return ActionResult.bad(f"动词 '{verb}' 未绑定 handler")
        try:
            js = v.handler(self, instance, **params)  # handler 返回 JS 表达式字符串
        except Exception as exc:  # noqa: BLE001
            return ActionResult.bad(f"{type(exc).__name__}: {exc}")
        if self.evaluator is None:
            return ActionResult.good({"dry_run": True, "js": js},
                                     logs=["未绑定 CDP evaluator，返回待执行 JS（离线校验）"])
        return ActionResult.good(self.evaluator(js), logs=[f"CDP eval: {js[:120]}"])

    def shutdown(self, instance: Instance) -> None:
        instance.alive = False
