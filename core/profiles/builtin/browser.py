"""浏览器画像（级别①·CDP · 收编 Devin-Remote AI GUI 体系的 Web 语义面）。

把 vendored agentctl.browser（CDP 直驱·语义优先·闭环等待）做成一个通用层画像：
Agent 操作网页不再走「截图+坐标点击」，而是 selector/可见文本级动词（click/type_text/
get_text/wait_visible…），与 Devin-Remote dao-bridge 的 browser_* 工具面同源同語义。

浏览器实例经 browser_factory 注入（真机接本地 Chrome CDP 端口；未注入即 dry-run
回显将执行的动作，Linux/CI 可离线单测）——守约：不改 vendored 源，只做薄绑定。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.adapter.base import ActionResult, AppAdapter, Instance
from core.profiles.schema import AppProfile, AutomationLevel, Verb

# 暴露为动词的 agentctl.browser 方法子集（语义优先的高价值面；名字与上游一致）。
_METHODS: dict[str, tuple[str, dict[str, str]]] = {
    "navigate": ("导航到 URL 并等 DOM 就绪", {"url": "目标 URL"}),
    "click": ("点击元素(CSS selector 或 by_text=可见文本)",
              {"selector": "CSS 选择器或可见文本", "by_text": "true=按可见文本定位"}),
    "type_text": ("聚焦输入框后原子写入文本(insertText·免逐键竞态)",
                  {"selector": "输入框选择器", "text": "要写入的文本", "clear": "true=先清空"}),
    "get_text": ("读取元素文本", {"selector": "CSS 选择器"}),
    "exists": ("元素是否存在", {"selector": "CSS 选择器"}),
    "is_visible": ("元素是否可见", {"selector": "CSS 选择器"}),
    "wait_visible": ("等待元素可见(显式闭环等待·代替 sleep)",
                     {"selector": "CSS 选择器", "timeout": "秒"}),
    "hover": ("悬停元素", {"selector": "CSS 选择器"}),
    "scroll_into_view": ("滚动使元素入视口", {"selector": "CSS 选择器"}),
    "select_option": ("下拉框选择", {"selector": "select 选择器", "value": "选项值"}),
    "press_key": ("按一个键(Enter/Escape/Tab…)", {"key": "键名"}),
    "eval": ("在页面上下文执行 JS 表达式", {"expr": "JS 表达式"}),
    "pages": ("列出全部页面(标签)", {}),
    "switch_page": ("切换到 URL/标题匹配的页面", {"match": "URL/标题子串"}),
    "url": ("当前页面 URL", {}),
    "title": ("当前页面标题", {}),
    "screenshot": ("整页截图到磁盘(证据·非操作依据)", {"path": "保存路径"}),
}

_ARG_ORDER: dict[str, tuple[str, ...]] = {
    "navigate": ("url",),
    "click": ("selector", "by_text"),
    "type_text": ("selector", "text", "clear"),
    "get_text": ("selector",),
    "exists": ("selector",),
    "is_visible": ("selector",),
    "wait_visible": ("selector", "timeout"),
    "hover": ("selector",),
    "scroll_into_view": ("selector",),
    "select_option": ("selector", "value"),
    "press_key": ("key",),
    "eval": ("expr",),
    "pages": (),
    "switch_page": ("match",),
    "url": (),
    "title": (),
    "screenshot": ("path",),
}

_KWONLY = {("select_option", "value")}


class BrowserCdpAdapter(AppAdapter):
    """薄绑定：动词名=agentctl.browser 方法名，参数按位传递。"""

    level = AutomationLevel.CDP

    def __init__(self, profile: AppProfile,
                 browser_factory: Optional[Callable[[], Any]] = None) -> None:
        super().__init__(profile)
        self.browser_factory = browser_factory
        self._browser: Any = None

    def launch(self, workdir: str, **kwargs: Any) -> Instance:
        inst = Instance(app_id=self.profile.app_id, workdir=workdir, meta=dict(kwargs))
        if self.browser_factory is not None:
            self._browser = self.browser_factory()
        return inst

    def invoke(self, instance: Instance, verb: str, **params: Any) -> ActionResult:
        v = self.profile.verb(verb)
        if v is None:
            return ActionResult.bad(
                f"未知动词 '{verb}'，可用: {[x.name for x in self.profile.verbs]}")
        name = v.name
        order = _ARG_ORDER.get(name, ())
        args = []
        kwargs: dict[str, Any] = {}
        for key in order:
            if key not in params:
                continue
            if (name, key) in _KWONLY:
                kwargs[key] = params[key]
            else:
                args.append(params[key])
        if self._browser is None:
            return ActionResult.good(
                {"dry_run": True, "method": name, "args": args, "kwargs": kwargs},
                logs=["未绑定 CDP 浏览器，dry-run 回显动作（离线校验）"])
        try:
            fn = getattr(self._browser, name)
            return ActionResult.good(fn(*args, **kwargs), logs=[f"browser.{name}"])
        except Exception as exc:  # noqa: BLE001 - 单动词失败如实回报
            return ActionResult.bad(f"{type(exc).__name__}: {exc}")

    def shutdown(self, instance: Instance) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        instance.alive = False


def make_browser_factory(port: int = 29229) -> Callable[[], Any]:
    """真机工厂：接本地 Chrome CDP 端口（vendored agentctl.browser.Browser）。"""
    def factory() -> Any:
        import os
        import sys
        vendor = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "gui", "agentctl"))
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        import browser as _b  # noqa: E402 - vendored 模块按目录导入
        return _b.Browser(port=port)
    return factory


PROFILE = AppProfile(
    app_id="browser",
    display_name="浏览器 (Chrome CDP · AI GUI 语义面)",
    level=AutomationLevel.CDP,
    launch={"cdp_port": 29229},
    file_conventions={},
    source_repo="Devin-Remote（agentctl vendored）",
    tags=("cdp", "web", "level1", "ai-gui"),
    layer="universal",
    mention="browser",
    prompt_snippet=(
        "网页操作走 CDP 语义面：selector/可见文本级动词 + 显式闭环等待（wait_visible），"
        "绝不截图+坐标点击。截图仅作证据，不作操作依据。"
    ),
    verbs=[
        Verb(name, summary, params) for name, (summary, params) in _METHODS.items()
    ],
)


def _ADAPTER(profile: AppProfile,
             browser_factory: Optional[Callable[[], Any]] = None) -> BrowserCdpAdapter:
    return BrowserCdpAdapter(profile, browser_factory=browser_factory)
