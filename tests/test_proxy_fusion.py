"""三插件融合 · Proxy Pro 提示词引擎联动模式契约（跨语言集成）。

验证合三为一的枢纽：Python 侧 ModeManager 写 ~/.dao/mode.json 契约 →
vendored JS 引擎 sp_invert.js 据此道化官方 SP：
  · coding 模式 → 官方原貌不道化（invert 跳过）
  · 其余模式 → 官方标记被替换为帛书经文，overlay 追加
node 缺失时跳过（CI Linux 常自带 node；纯逻辑单测不依赖本用例）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from core.agent.modes import ModeManager
from core.profiles.builtin import build_default_registry

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SP = os.path.join(_REPO, "ide", "vscode", "dao-proxy-pro", "sp_invert.js")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not os.path.exists(_SP),
    reason="需要 node 与 vendored sp_invert.js",
)

_OFFICIAL = (
    "You are Cascade, the AI coding assistant. "
    "<tool>create_memory</tool> Follow the USER's instructions."
)


def _invert_under_home(home: str) -> str:
    """在指定 HOME 下用 vendored 引擎道化官方 SP，返回结果（null → 空串）。"""
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    script = (
        "const sp=require(process.argv[1]);"
        "const out=sp.invertSP(process.argv[2]);"
        "process.stdout.write(out==null?'':out);"
    )
    r = subprocess.run(
        ["node", "-e", script, _SP, _OFFICIAL],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_coding_mode_passthrough(tmp_path):
    mm = ModeManager(build_default_registry(), state_path=str(tmp_path / ".dao" / "mode.json"))
    mm.set("coding")
    assert _invert_under_home(str(tmp_path)) == ""  # 官方原貌 · 引擎跳过道化


def test_windows_mode_inverts_with_overlay(tmp_path):
    mm = ModeManager(build_default_registry(), state_path=str(tmp_path / ".dao" / "mode.json"))
    mode = mm.set("windows")
    out = _invert_under_home(str(tmp_path))
    assert out and "Cascade" not in out            # 官方标记已被道化替换
    assert "德" in out or "道" in out               # 帛书经文已注入
    assert mode.prompt_overlay.strip()[:8] in out   # 模式 overlay 已追加


def test_contract_has_overlay_field(tmp_path):
    mm = ModeManager(build_default_registry(), state_path=str(tmp_path / ".dao" / "mode.json"))
    mm.set("windows")
    data = json.loads((tmp_path / ".dao" / "mode.json").read_text(encoding="utf-8"))
    assert set(data) >= {"mode", "name", "tool_policy", "replace_official", "overlay", "updated"}
