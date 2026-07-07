"""FreeCAD 画像（级别① · FreeCADCmd 无头脚本，或 _fc_remote_server HTTP）。

收编自 Dao-3D-Modeling-Agent（freecad_backend 60+ ops / _fc_remote_server :18920 / OCCT 内核）。
FreeCAD 可用 FreeCADCmd 跑 Python 宏无头建模、导出 STEP/STL → 天然隔离并行。
"""
from __future__ import annotations

import os

from core.adapter.base import ActionResult
from core.adapter.subprocess_api import SubprocessApiAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb


def _version(adapter, instance, **_):
    return adapter.run_cli(["FreeCADCmd", "--version"], instance)


def _run_macro(adapter, instance, script: str = "", macro_path: str = "", **_):
    """执行一段 FreeCAD Python 宏（script 内联 或 macro_path 文件）。"""
    if not macro_path:
        if not script:
            return ActionResult.bad("需提供 script 或 macro_path")
        macro_path = os.path.join(instance.workdir, "_macro.py")
        with open(macro_path, "w", encoding="utf-8") as fh:
            fh.write(script)
    return adapter.run_cli(["FreeCADCmd", macro_path], instance, timeout=180)


def _export_step(adapter, instance, fcstd: str, out: str = "out.step", **_):
    script = (
        "import FreeCAD, Part\n"
        f"doc = FreeCAD.open(r'{fcstd}')\n"
        "objs = [o for o in doc.Objects if hasattr(o, 'Shape')]\n"
        f"Part.export(objs, r'{out}')\n"
        "print('exported', len(objs), 'objects')\n"
    )
    return _run_macro(adapter, instance, script=script)


PROFILE = AppProfile(
    app_id="freecad",
    display_name="FreeCAD (3D 参数化建模)",
    level=AutomationLevel.API,
    launch={"cli": "FreeCADCmd", "gui_http": 18920, "headless": True},
    file_conventions={"project": ".FCStd", "outputs": ["step", "stl", "brep", "iges"]},
    source_repo="Dao-3D-Modeling-Agent (freecad_backend / _fc_remote_server)",
    tags=("cad", "3d", "headless"),
    prompt_snippet=(
        "FreeCAD 用 FreeCADCmd 跑 Python 宏无头建模，或经 _fc_remote_server(:18920) 驱动 GUI 展示。"
        "参数化建模走 Part/PartDesign API；导出 STEP/STL/BREP 皆脚本可得。"
    ),
    verbs=[
        Verb("version", "查询 FreeCAD 版本", handler=_version),
        Verb("run_macro", "执行 FreeCAD Python 宏（内联 script 或 macro_path）",
             {"script": "内联 Python", "macro_path": "宏文件路径"}, handler=_run_macro),
        Verb("export_step", "打开 .FCStd 并导出 STEP",
             {"fcstd": ".FCStd 路径", "out": "输出 .step"}, handler=_export_step),
    ],
)
_ADAPTER = SubprocessApiAdapter
