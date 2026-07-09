"""跨领域工程交接状态机（板块四 · 终局基础设施）。

终局形态：用户全栈提需求（PCB 完了接 3D，3D 完了接下一环节），Agent 自主感知
可用领域模块、择路执行、完工交接。本模块把"交接"从提示词层约定落为状态机：

  工程(project) = 有序阶段(stage)序列，每阶段绑定一个领域 app_id（或整机通用层）
  与一句目标；当前阶段完工 → advance(产物清单) → 状态机给出下一环节的
  交接指引（@句柄 + 建议专精模式 mode.set domain:<app_id>），全程持久化 JSON，
  拒绝时如实回报（不臆造、不静默）。

纯标准库、纯逻辑，Linux/CI 即可单测。
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

from core.profiles.registry import ProfileRegistry

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class HandoffFlow:
    """工程编排：create → status → advance…（每阶段完工交接下一环节）。"""

    def __init__(self, registry: ProfileRegistry, root: str) -> None:
        self.registry = registry
        self.root = root

    # —— 持久化 ——
    def _path(self, project_id: str) -> str:
        return os.path.join(self.root, project_id + ".json")

    def _load(self, project_id: str) -> Optional[dict]:
        try:
            with open(self._path(project_id), encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _save(self, proj: dict) -> None:
        os.makedirs(self.root, exist_ok=True)
        proj["updated"] = int(time.time())
        with open(self._path(proj["project_id"]), "w", encoding="utf-8") as fh:
            json.dump(proj, fh, ensure_ascii=False, indent=2)

    # —— 编排 ——
    def create(self, project_id: str, goal: str, stages: list[dict]) -> dict:
        """建一条工程流水线。stages: [{"app_id": "kicad", "goal": "导出 gerber"}, …]。

        app_id 必须是已注册画像（或省略=整机通用层）；未注册者如实拒绝。
        """
        if not _ID.match(project_id or ""):
            return {"error": f"非法 project_id: {project_id!r}（字母数字._-，≤64）"}
        if self._load(project_id) is not None:
            return {"error": f"工程已存在: {project_id}"}
        if not stages:
            return {"error": "至少要一个阶段"}
        known = set(self.registry.app_ids())
        norm: list[dict] = []
        for i, st in enumerate(stages):
            app_id = str(st.get("app_id") or "").strip()
            if app_id and app_id not in known:
                return {"error": f"阶段{i + 1} 领域未注册: {app_id}（可用: {sorted(known)}）"}
            norm.append({
                "index": i,
                "app_id": app_id,            # 空 = 整机通用层
                "goal": str(st.get("goal") or ""),
                "status": "pending",         # pending | active | done
                "artifacts": [],
                "note": "",
            })
        norm[0]["status"] = "active"
        proj = {
            "project_id": project_id,
            "goal": goal,
            "stages": norm,
            "status": "active",              # active | done
            "created": int(time.time()),
        }
        self._save(proj)
        return self.status(project_id)

    def advance(self, project_id: str, artifacts: Optional[list] = None,
                note: str = "") -> dict:
        """当前阶段完工：登记产物 → 交接下一环节（给出 @句柄与建议模式）。"""
        proj = self._load(project_id)
        if proj is None:
            return {"error": f"无此工程: {project_id}"}
        if proj.get("status") == "done":
            return {"error": f"工程已完工: {project_id}"}
        stages = proj["stages"]
        cur = next((s for s in stages if s["status"] == "active"), None)
        if cur is None:
            return {"error": f"工程无活动阶段（状态损坏）: {project_id}"}
        cur["status"] = "done"
        cur["artifacts"] = [str(a) for a in (artifacts or [])]
        cur["note"] = str(note or "")
        nxt = next((s for s in stages if s["status"] == "pending"), None)
        if nxt is not None:
            nxt["status"] = "active"
        else:
            proj["status"] = "done"
        self._save(proj)
        return self.status(project_id)

    def status(self, project_id: str) -> dict:
        proj = self._load(project_id)
        if proj is None:
            return {"error": f"无此工程: {project_id}"}
        cur = next((s for s in proj["stages"] if s["status"] == "active"), None)
        out = dict(proj)
        out["current"] = cur
        out["handoff"] = self._handoff_hint(cur) if cur is not None else None
        if proj["status"] == "done":
            out["handoff"] = {"summary": "全部环节完工。产物清单见各阶段 artifacts。"}
        return out

    def list(self) -> dict:
        items: list[dict] = []
        if os.path.isdir(self.root):
            for name in sorted(os.listdir(self.root)):
                if not name.endswith(".json"):
                    continue
                proj = self._load(name[:-5])
                if proj:
                    items.append({
                        "project_id": proj["project_id"],
                        "goal": proj.get("goal", ""),
                        "status": proj.get("status", ""),
                        "stages": len(proj.get("stages") or []),
                    })
        return {"projects": items}

    def active_snippet(self) -> str:
        """活动工程的交接指引拼成提示词片段（供系统提示注入，Agent 无需另查 API）。"""
        lines: list[str] = []
        for item in self.list()["projects"]:
            if item["status"] != "active":
                continue
            st = self.status(item["project_id"])
            cur, hint = st.get("current"), st.get("handoff") or {}
            if not cur:
                continue
            done = sum(1 for s in st["stages"] if s["status"] == "done")
            lines.append(
                f"- 工程 {st['project_id']}（{st.get('goal', '')}）"
                f"第 {done + 1}/{len(st['stages'])} 环节：{hint.get('summary', '')}")
        if not lines:
            return ""
        return "进行中的跨领域工程（当前环节完工后用 project.advance 交接）：\n" + "\n".join(lines)

    # —— 交接指引（拿给 Agent 直接照做）——
    def _handoff_hint(self, stage: dict) -> dict:
        app_id = stage.get("app_id") or ""
        hint: dict = {"goal": stage.get("goal", "")}
        prof = self.registry.get(app_id) if app_id else None
        if prof is not None:
            hint["handle"] = "@" + prof.handle
            hint["suggest_mode"] = f"domain:{prof.app_id}"
            hint["verbs"] = [v.name for v in prof.verbs]
            hint["summary"] = (f"当前环节 {prof.display_name}：@{prof.handle} 唤起领域层，"
                               f"或 mode.set {hint['suggest_mode']} 切专精模式；"
                               f"完工后 project.advance 交接下一环节。")
        else:
            hint["handle"] = ""
            hint["suggest_mode"] = "windows"
            hint["summary"] = "当前环节落整机通用层；完工后 project.advance 交接下一环节。"
        return hint
