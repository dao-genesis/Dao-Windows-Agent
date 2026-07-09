"""外部子插件远程适配器（级别①·RPC 收编）。

一个独立的 VS Code 子插件（如 FreeCAD/KiCad 专用扩展）把自己的能力经一个本地 HTTP
端点暴露；本适配器把它的动词代理进本体系——对 Agent 而言与内置画像完全一致（@ 唤起、
invoke 执行），实现"主插件自动识别并调度所有子插件"的闭环。

纯 stdlib（urllib），零第三方依赖。transport 可注入以便单测（不起真网络）。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Optional

from core.adapter.base import ActionResult, AppAdapter, Instance
from core.profiles.schema import AppProfile, AutomationLevel

# transport(url, payload, token, timeout) -> dict：默认走 urllib，可注入假实现单测。
Transport = Callable[[str, dict, str, float], dict]


def _http_transport(url: str, payload: dict, token: str, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 本地子插件端点
        return json.loads(resp.read().decode("utf-8") or "{}")


class RemoteSubpluginAdapter(AppAdapter):
    """把外部子插件的动词经 RPC 代理成本体系动词。"""

    level = AutomationLevel.API

    def __init__(self, profile: AppProfile, invoke_url: str, token: str = "",
                 transport: Optional[Transport] = None, timeout: float = 120.0) -> None:
        super().__init__(profile)
        self.invoke_url = invoke_url
        self.token = token
        self.timeout = timeout
        self._transport: Transport = transport or _http_transport

    def launch(self, workdir: str, **kwargs: Any) -> Instance:
        # 子插件常驻，无需本地启动；仅记录会话上下文。
        return Instance(app_id=self.profile.app_id, workdir=workdir,
                        meta={"invoke_url": self.invoke_url})

    def invoke(self, instance: Instance, verb: str, **params: Any) -> ActionResult:
        if self.profile.verb(verb) is None:
            return ActionResult.bad(f"[{self.profile.app_id}] 未知动词: {verb}")
        payload = {"app_id": self.profile.app_id, "verb": verb,
                   "params": params, "workdir": instance.workdir}
        try:
            resp = self._transport(self.invoke_url, payload, self.token, self.timeout)
        except Exception as e:  # noqa: BLE001 - RPC 失败如实回报，不吞
            return ActionResult.bad(f"子插件 RPC 失败: {e}")
        if not isinstance(resp, dict):
            return ActionResult.bad("子插件返回非法（非 JSON 对象）")
        if resp.get("ok"):
            return ActionResult.good(resp.get("value"), logs=resp.get("logs") or [])
        return ActionResult.bad(resp.get("error") or "子插件返回 ok=false", logs=resp.get("logs") or [])

    def shutdown(self, instance: Instance) -> None:
        instance.alive = False
