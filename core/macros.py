"""宏沉淀层：把模型规划成功的动词序列固化成新的复合动词（经验沉淀·类 Devin skills）。

道法自然·反者道之动：工具层残缺 R1 指出——现有动词偏"原子"（open/type/click/exec），
缺"分子"级复合动词；弱模型在长链上每步一次往返易崩。解法不是加胖动词，而是**把已被
证明成功的动词序列录下来、固化成一个新动词**，下次一句话即整段重放——经验沉淀成能力，
"為學者日益"。

三段式（与 ha-copilot search/describe/run 同源思想）：
    record   录制：begin(name) 起录 → 每成功一步 append → commit 固化（仅当全程无败步）。
    describe list()/get()：查已沉淀的宏及其步骤。
    run      重放：按注入的 invoker 逐步执行；任一步失败即如实停下并回报（不假装成功）。

纯逻辑 + 纯标准库：持久化为 JSON（缺省 ~/.dao/macros.json），invoker 由上层注入
（BridgeService 传 session_invoke），故录制/重放皆可离线单测，不触真机。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


def default_macros_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".dao", "macros.json")


@dataclass
class MacroStep:
    app_id: str
    verb: str
    params: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"app_id": self.app_id, "verb": self.verb, "params": dict(self.params)}

    @staticmethod
    def from_dict(d: dict) -> "MacroStep":
        return MacroStep(app_id=str(d.get("app_id", "")),
                         verb=str(d.get("verb", "")),
                         params=dict(d.get("params") or {}))


@dataclass
class Macro:
    name: str
    steps: List[MacroStep]
    description: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "steps": [s.to_dict() for s in self.steps],
        }

    @staticmethod
    def from_dict(d: dict) -> "Macro":
        return Macro(
            name=str(d.get("name", "")),
            description=str(d.get("description", "")),
            created_at=float(d.get("created_at", 0.0)),
            steps=[MacroStep.from_dict(s) for s in (d.get("steps") or [])],
        )


# 录制中的一步（含成败）——commit 时仅当全程无败步才固化，避免把错误路径沉淀成经验。
@dataclass
class _Recording:
    name: str
    steps: List[MacroStep] = field(default_factory=list)
    had_failure: bool = False


# invoker 契约：invoker(app_id, verb, params) -> {"ok": bool, ...}
Invoker = Callable[[str, str, dict], dict]


class MacroStore:
    """宏的持久化仓 + 录制缓冲 + 重放引擎（纯逻辑，可离线单测）。"""

    def __init__(self, path: Optional[str] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.path = path or default_macros_path()
        self._clock = clock
        self._macros: Dict[str, Macro] = {}
        self._recordings: Dict[str, _Recording] = {}
        self._load()

    # --- 持久化 ---
    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        for d in (data.get("macros") or []):
            m = Macro.from_dict(d)
            if m.name:
                self._macros[m.name] = m

    def _flush(self) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"macros": [m.to_dict() for m in self._macros.values()]},
                      fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # --- 录制 ---
    def begin(self, name: str) -> dict:
        if not name:
            raise ValueError("宏名不能为空")
        self._recordings[name] = _Recording(name=name)
        return {"recording": name, "steps": 0}

    def record_step(self, name: str, app_id: str, verb: str,
                    params: Optional[dict] = None, ok: bool = True) -> dict:
        """录一步。ok=False 标记该录制含败步——commit 将拒绝固化错误路径。"""
        rec = self._recordings.get(name)
        if rec is None:
            raise KeyError(f"未在录制: {name}（先 begin）")
        if not ok:
            rec.had_failure = True
        else:
            rec.steps.append(MacroStep(app_id=app_id, verb=verb, params=dict(params or {})))
        return {"recording": name, "steps": len(rec.steps), "had_failure": rec.had_failure}

    def commit(self, name: str, description: str = "") -> dict:
        """固化录制为宏——仅当全程无败步且至少一步成功。否则弃录并如实说明。"""
        rec = self._recordings.pop(name, None)
        if rec is None:
            raise KeyError(f"未在录制: {name}")
        if rec.had_failure:
            return {"ok": False, "error": f"录制 {name} 含失败步，拒绝沉淀错误路径（已弃录）"}
        if not rec.steps:
            return {"ok": False, "error": f"录制 {name} 无成功步可固化（已弃录）"}
        macro = Macro(name=name, steps=list(rec.steps),
                      description=description, created_at=self._clock())
        self._macros[name] = macro
        self._flush()
        return {"ok": True, "macro": macro.to_dict()}

    def cancel(self, name: str) -> dict:
        return {"cancelled": self._recordings.pop(name, None) is not None}

    # --- 直存（不经录制，供已知序列一次性沉淀） ---
    def save(self, name: str, steps: List[dict], description: str = "") -> dict:
        if not name:
            raise ValueError("宏名不能为空")
        parsed = [MacroStep.from_dict(s) for s in (steps or [])]
        parsed = [s for s in parsed if s.app_id and s.verb]
        if not parsed:
            return {"ok": False, "error": "无有效步骤（每步需 app_id 与 verb）"}
        macro = Macro(name=name, steps=parsed, description=description,
                      created_at=self._clock())
        self._macros[name] = macro
        self._flush()
        return {"ok": True, "macro": macro.to_dict()}

    # --- 查 / 删 ---
    def list(self) -> dict:
        return {"macros": [
            {"name": m.name, "description": m.description,
             "steps": len(m.steps), "created_at": m.created_at}
            for m in sorted(self._macros.values(), key=lambda x: x.name)
        ]}

    def get(self, name: str) -> Optional[dict]:
        m = self._macros.get(name)
        return m.to_dict() if m else None

    def delete(self, name: str) -> dict:
        existed = self._macros.pop(name, None) is not None
        if existed:
            self._flush()
        return {"deleted": existed}

    # --- 重放 ---
    def run(self, name: str, invoker: Invoker,
            overrides: Optional[Dict[int, dict]] = None) -> dict:
        """按注入的 invoker 逐步重放宏。任一步 ok=False 即停下（不续跑错误链）。

        overrides: {步序号: {参数覆盖}}，令固化的宏可带参重放（如换目标文件路径）。
        """
        macro = self._macros.get(name)
        if macro is None:
            return {"ok": False, "error": f"无此宏: {name}（可用: {sorted(self._macros)}）"}
        overrides = overrides or {}
        results = []
        ok_all = True
        for idx, step in enumerate(macro.steps):
            params = dict(step.params)
            if idx in overrides:
                params.update(overrides[idx])
            res = invoker(step.app_id, step.verb, params)
            step_ok = bool(isinstance(res, dict) and res.get("ok"))
            results.append({"step": idx, "app_id": step.app_id, "verb": step.verb,
                            "ok": step_ok, "result": res})
            if not step_ok:
                ok_all = False
                break
        return {"ok": ok_all, "macro": name, "ran": len(results),
                "total": len(macro.steps), "results": results}


__all__ = ["Macro", "MacroStep", "MacroStore", "default_macros_path"]
