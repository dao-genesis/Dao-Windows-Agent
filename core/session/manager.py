"""会话模型：每个 IDE 窗口 = 一个 session（类虚拟机实例）。

一个 session 持有一组绑定的软件实例；开 N 个 IDE 窗口 = N 个隔离 session。
session 之间互不干扰；与用户真实桌面并行（级别① 无头，天然隔离）。
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from core.adapter.base import ActionResult, AppAdapter, Instance
from core.profiles.registry import ProfileRegistry


@dataclass
class Session:
    session_id: str
    workdir: str
    created_at: float = field(default_factory=time.time)
    instances: dict[str, Instance] = field(default_factory=dict)  # app_id -> Instance
    meta: dict[str, Any] = field(default_factory=dict)


class SessionManager:
    """类虚拟机会话生命周期管理。"""

    def __init__(self, registry: ProfileRegistry, root: str = "/tmp/dao-win/sessions"):
        self.registry = registry
        self.root = root
        self.sessions: dict[str, Session] = {}
        self._adapters: dict[str, AppAdapter] = {}  # session_id:app_id -> adapter

    def create(self, session_id: Optional[str] = None) -> Session:
        sid = session_id or f"vm_{uuid.uuid4().hex[:8]}"
        if sid in self.sessions:
            return self.sessions[sid]
        workdir = os.path.join(self.root, sid)
        os.makedirs(workdir, exist_ok=True)
        sess = Session(session_id=sid, workdir=workdir)
        self.sessions[sid] = sess
        return sess

    def list(self) -> list[str]:
        return list(self.sessions.keys())

    def open_app(self, session_id: str, app_id: str, **kwargs: Any) -> ActionResult:
        sess = self.sessions.get(session_id)
        if sess is None:
            return ActionResult.bad(f"会话不存在: {session_id}")
        adapter = self.registry.make_adapter(app_id)
        if adapter is None:
            return ActionResult.bad(f"无此应用画像: {app_id}（可用: {self.registry.app_ids()}）")
        app_workdir = os.path.join(sess.workdir, app_id)
        kwargs.setdefault("session_id", session_id)
        inst = adapter.launch(app_workdir, **kwargs)
        sess.instances[app_id] = inst
        self._adapters[f"{session_id}:{app_id}"] = adapter
        return ActionResult.good({"session_id": session_id, "app_id": app_id, "workdir": app_workdir})

    def invoke(self, session_id: str, app_id: str, verb: str, **params: Any) -> ActionResult:
        sess = self.sessions.get(session_id)
        if sess is None:
            return ActionResult.bad(f"会话不存在: {session_id}")
        inst = sess.instances.get(app_id)
        adapter = self._adapters.get(f"{session_id}:{app_id}")
        if inst is None or adapter is None:
            return ActionResult.bad(f"应用未在会话内打开: {app_id}（先 open_app）")
        return adapter.invoke(inst, verb, **params)

    def destroy(self, session_id: str) -> ActionResult:
        sess = self.sessions.pop(session_id, None)
        if sess is None:
            return ActionResult.bad(f"会话不存在: {session_id}")
        for app_id, inst in sess.instances.items():
            adapter = self._adapters.pop(f"{session_id}:{app_id}", None)
            if adapter is not None:
                try:
                    adapter.shutdown(inst)
                except Exception:  # noqa: BLE001
                    pass
        return ActionResult.good({"destroyed": session_id})
