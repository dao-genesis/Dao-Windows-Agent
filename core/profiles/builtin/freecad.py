"""FreeCAD 画像（级别① · FreeCADCmd 无头脚本，或 _fc_remote_server HTTP）。

收编自 Dao-3D-Modeling-Agent（freecad_backend 60+ ops / _fc_remote_server :18920 / OCCT 内核）。
FreeCAD 可用 FreeCADCmd 跑 Python 宏无头建模、导出 STEP/STL → 天然隔离并行。
"""
from __future__ import annotations

import glob
import os
import shutil

from core.adapter.base import ActionResult
from core.adapter.subprocess_api import SubprocessApiAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb


def _fc_bin() -> str:
    """解析 FreeCAD 无头可执行：先 PATH，再探 Windows 标准装机目录。

    winget/官方安装器装到 `C:\\Program Files\\FreeCAD <版本>\\bin` 且不改 PATH，
    仅靠 which 会漏找（真机冷启动实测）。"""
    for name in ("FreeCADCmd", "freecadcmd", "freecad-cmd"):
        if shutil.which(name):
            return name
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("LOCALAPPDATA", "") + r"\Programs"):
            hits = sorted(glob.glob(os.path.join(base, "FreeCAD*", "bin", "FreeCADCmd.exe")),
                          reverse=True)
            if hits:
                return hits[0]
    return "FreeCADCmd"


def _version(adapter, instance, **_):
    return adapter.run_cli([_fc_bin(), "--version"], instance)


def _run_macro(adapter, instance, script: str = "", macro_path: str = "", **_):
    """执行一段 FreeCAD Python 宏（script 内联 或 macro_path 文件）。"""
    if not macro_path:
        if not script:
            return ActionResult.bad("需提供 script 或 macro_path")
        macro_path = os.path.join(instance.workdir, "_macro.py")
        with open(macro_path, "w", encoding="utf-8") as fh:
            fh.write(script)
    return adapter.run_cli([_fc_bin(), macro_path], instance, timeout=180)


def _export_step(adapter, instance, fcstd: str, out: str = "out.step", **_):
    script = (
        "import FreeCAD, Part\n"
        f"doc = FreeCAD.open(r'{fcstd}')\n"
        "objs = [o for o in doc.Objects if hasattr(o, 'Shape')]\n"
        f"Part.export(objs, r'{out}')\n"
        "print('exported', len(objs), 'objects')\n"
    )
    return _run_macro(adapter, instance, script=script)


def _export_stl(adapter, instance, fcstd: str, out: str = "out.stl", **_):
    script = (
        "import FreeCAD, Mesh\n"
        f"doc = FreeCAD.open(r'{fcstd}')\n"
        "objs = [o for o in doc.Objects if hasattr(o, 'Shape')]\n"
        f"Mesh.export(objs, r'{out}')\n"
        "print('exported', len(objs), 'objects')\n"
    )
    return _run_macro(adapter, instance, script=script)


def _run_ops(adapter, instance, ops=None, **_):
    """执行 freecad_backend.run_ops 风格的算子序列（需 freecad_backend 在 PYTHONPATH）。

    ops 例：[{"op":"make_box","id":"b","L":20,"W":10,"H":5},
             {"op":"export_stl","shape":"b","path":"out.stl"}]
    """
    import json as _json
    if not ops:
        return ActionResult.bad("需提供 ops 列表")
    cmd_path = os.path.join(instance.workdir, "_ops.json")
    with open(cmd_path, "w", encoding="utf-8") as fh:
        _json.dump({"ops": ops}, fh, ensure_ascii=True)
    script = (
        "import json, os, sys\n"
        # freecad_backend 随冷启动落地 <部署根>\tools；FreeCADCmd 的 sys.path 不含它，须自补
        "for _p in (os.environ.get('DAO_FREECAD_TOOLS', ''),\n"
        "           os.path.join(os.environ.get('DAO_WIN_HOME', r'C:\\dao_win'), 'tools'),\n"
        "           os.path.join(os.getcwd(), 'tools')):\n"
        "    if _p and os.path.isdir(_p) and _p not in sys.path:\n"
        "        sys.path.insert(0, _p)\n"
        "from freecad_backend import run_ops\n"
        f"_c = json.load(open(r'{cmd_path}', encoding='utf-8'))\n"
        "print(json.dumps(run_ops(_c.get('ops', [])), ensure_ascii=True))\n"
    )
    return _run_macro(adapter, instance, script=script)


def _export_iges(adapter, instance, fcstd: str, out: str = "out.iges", **_):
    script = (
        "import FreeCAD, Part\n"
        f"doc = FreeCAD.open(r'{fcstd}')\n"
        "objs = [o for o in doc.Objects if hasattr(o, 'Shape')]\n"
        f"Part.export(objs, r'{out}')\n"
        "print('exported', len(objs), 'objects')\n"
    )
    return _run_macro(adapter, instance, script=script)


def _export_brep(adapter, instance, fcstd: str, out: str = "out.brep", **_):
    script = (
        "import FreeCAD\n"
        f"doc = FreeCAD.open(r'{fcstd}')\n"
        "objs = [o for o in doc.Objects if hasattr(o, 'Shape')]\n"
        "import Part\n"
        "shape = Part.makeCompound([o.Shape for o in objs])\n"
        f"shape.exportBrep(r'{out}')\n"
        "print('exported compound of', len(objs), 'objects')\n"
    )
    return _run_macro(adapter, instance, script=script)


def _inspect_doc(adapter, instance, fcstd: str, **_):
    """列出 .FCStd 文档对象树（名称/类型/包围盒），供 agent 感知模型结构。"""
    script = (
        "import json, FreeCAD\n"
        f"doc = FreeCAD.open(r'{fcstd}')\n"
        "items = []\n"
        "for o in doc.Objects:\n"
        "    it = {'name': o.Name, 'label': o.Label, 'type': o.TypeId}\n"
        "    if hasattr(o, 'Shape') and o.Shape and not o.Shape.isNull():\n"
        "        bb = o.Shape.BoundBox\n"
        "        it['bbox'] = [bb.XLength, bb.YLength, bb.ZLength]\n"
        "        it['volume'] = o.Shape.Volume\n"
        "    items.append(it)\n"
        "print(json.dumps(items, ensure_ascii=True))\n"
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
        Verb("run_ops", "执行算子序列(make_box/export_stl 等，freecad_backend 风格)",
             {"ops": "算子列表(JSON)"}, handler=_run_ops, aliases=("ops",)),
        Verb("export_step", "打开 .FCStd 并导出 STEP",
             {"fcstd": ".FCStd 路径", "out": "输出 .step"}, handler=_export_step, aliases=("step",)),
        Verb("export_stl", "打开 .FCStd 并导出 STL 网格",
             {"fcstd": ".FCStd 路径", "out": "输出 .stl"}, handler=_export_stl, aliases=("stl",)),
        Verb("export_iges", "打开 .FCStd 并导出 IGES",
             {"fcstd": ".FCStd 路径", "out": "输出 .iges"}, handler=_export_iges, aliases=("iges",)),
        Verb("export_brep", "打开 .FCStd 并导出 BREP(OCCT 原生)",
             {"fcstd": ".FCStd 路径", "out": "输出 .brep"}, handler=_export_brep, aliases=("brep",)),
        Verb("inspect_doc", "感知 .FCStd 对象树(名称/类型/包围盒/体积, JSON)",
             {"fcstd": ".FCStd 路径"}, handler=_inspect_doc, aliases=("tree", "inspect")),
    ],
)
_ADAPTER = SubprocessApiAdapter
