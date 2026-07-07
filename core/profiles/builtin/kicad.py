"""KiCad 画像（级别① · kicad-cli / pcbnew Python，无头）。

收编自 Dao-PCB-Design-Agent 路线B（pcb_brain / kicad_origin）。
KiCad 提供 kicad-cli 与 pcbnew Python API，全流程无需 GUI → 天然隔离并行。
"""
from __future__ import annotations

import os

from core.adapter.base import ActionResult
from core.adapter.subprocess_api import SubprocessApiAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb


def _version(adapter, instance, **_):
    return adapter.run_cli(["kicad-cli", "version"], instance)


def _export_gerbers(adapter, instance, pcb: str, out_dir: str = "gerbers", **_):
    return adapter.run_cli(["kicad-cli", "pcb", "export", "gerbers", "-o", out_dir, pcb], instance)


def _export_drill(adapter, instance, pcb: str, out_dir: str = "gerbers", **_):
    return adapter.run_cli(["kicad-cli", "pcb", "export", "drill", "-o", out_dir + "/", pcb], instance)


def _export_pos(adapter, instance, pcb: str, out: str = "pos.csv", fmt: str = "csv", **_):
    return adapter.run_cli(["kicad-cli", "pcb", "export", "pos", "-o", out, "--format", fmt, pcb], instance)


def _export_step(adapter, instance, pcb: str, out: str = "board.step", **_):
    return adapter.run_cli(["kicad-cli", "pcb", "export", "step", "-o", out, pcb], instance)


def _render_3d(adapter, instance, pcb: str, out: str = "board.png", width: int = 1200, height: int = 900, **_):
    return adapter.run_cli(["kicad-cli", "pcb", "render", "-o", out,
                            "--width", str(width), "--height", str(height), pcb], instance)


def _run_drc(adapter, instance, pcb: str, out: str = "drc.json", **_):
    return adapter.run_cli(["kicad-cli", "pcb", "drc", "--format", "json", "-o", out, pcb], instance)


def _export_bom(adapter, instance, sch: str, out: str = "bom.csv", **_):
    return adapter.run_cli(["kicad-cli", "sch", "export", "bom", "-o", out, sch], instance)


def _export_netlist(adapter, instance, sch: str, out: str = "netlist.net", fmt: str = "kicadsexpr", **_):
    return adapter.run_cli(["kicad-cli", "sch", "export", "netlist",
                            "--format", fmt, "-o", out, sch], instance)


def _export_sch_pdf(adapter, instance, sch: str, out: str = "schematic.pdf", **_):
    return adapter.run_cli(["kicad-cli", "sch", "export", "pdf", "-o", out, sch], instance)


def _export_pcb_svg(adapter, instance, pcb: str, out: str = "board.svg",
                    layers: str = "F.Cu,B.Cu,Edge.Cuts", **_):
    return adapter.run_cli(["kicad-cli", "pcb", "export", "svg",
                            "--layers", layers, "-o", out, pcb], instance)


def _pcb_python(adapter, instance, script: str = "", macro_path: str = "", **_):
    """无头执行任意 pcbnew Python 脚本（解锁 kicad-cli 未覆盖的板级操作）。

    收编自 pcb_brain/kicad_native.py 的 pcbnew 直驱思路——载 board、改 net/track、
    跑原生 DRC、导 DSN/收 SES 等皆可写进 script。需 guest 内 KiCad 自带 Python 可用。
    """
    if not macro_path:
        if not script:
            return ActionResult.bad("需提供 script 或 macro_path")
        macro_path = os.path.join(instance.workdir, "_pcbnew.py")
        with open(macro_path, "w", encoding="utf-8") as fh:
            fh.write(script)
    # KiCad 自带解释器：Windows 装机后 kicad-cli 同目录的 python；退回系统 python 也可（已装 pcbnew）
    return adapter.run_cli(["python", macro_path], instance, timeout=180)


PROFILE = AppProfile(
    app_id="kicad",
    display_name="KiCad (PCB 设计)",
    level=AutomationLevel.API,
    launch={"cli": "kicad-cli", "headless": True},
    file_conventions={"project": ".kicad_pro", "pcb": ".kicad_pcb", "sch": ".kicad_sch",
                      "outputs": ["gerber", "step", "bom", "drc"]},
    source_repo="Dao-PCB-Design-Agent (路线B: pcb_brain/kicad_origin)",
    tags=("pcb", "eda", "headless"),
    prompt_snippet=(
        "KiCad 全流程用 kicad-cli / pcbnew Python 无头驱动，不依赖 GUI。"
        "工程文件 .kicad_pcb/.kicad_sch 即真源；导出 Gerber/STEP/BOM/DRC 皆有 CLI 子命令。"
    ),
    verbs=[
        Verb("version", "查询 KiCad 版本，验证 CLI 可用", handler=_version),
        Verb("export_gerbers", "从 .kicad_pcb 导出 Gerber 制造文件",
             {"pcb": ".kicad_pcb 路径", "out_dir": "输出目录"},
             handler=_export_gerbers, aliases=("gerber",)),
        Verb("export_drill", "导出钻孔 Excellon(.drl)",
             {"pcb": ".kicad_pcb 路径", "out_dir": "输出目录"}, handler=_export_drill, aliases=("drill",)),
        Verb("export_pos", "导出贴片坐标(Pick&Place)",
             {"pcb": ".kicad_pcb 路径", "out": "输出文件", "fmt": "csv/gerber"},
             handler=_export_pos, aliases=("pos", "pick_place")),
        Verb("export_step", "导出板子 3D STEP 模型",
             {"pcb": ".kicad_pcb 路径", "out": "输出 .step"}, handler=_export_step, aliases=("step",)),
        Verb("render_3d", "渲染板子 3D 视图为 PNG",
             {"pcb": ".kicad_pcb 路径", "out": "输出 .png", "width": "宽", "height": "高"},
             handler=_render_3d, aliases=("render",)),
        Verb("run_drc", "运行设计规则检查(DRC)，产出 JSON 报告",
             {"pcb": ".kicad_pcb 路径", "out": "报告路径"}, handler=_run_drc, aliases=("drc",)),
        Verb("export_bom", "从 .kicad_sch 导出物料清单(BOM CSV)",
             {"sch": ".kicad_sch 路径", "out": "输出 .csv"}, handler=_export_bom, aliases=("bom",)),
        Verb("export_netlist", "从 .kicad_sch 导出网表(netlist)",
             {"sch": ".kicad_sch 路径", "out": "输出文件", "fmt": "kicadsexpr/spice/…"},
             handler=_export_netlist, aliases=("netlist",)),
        Verb("export_sch_pdf", "把原理图 .kicad_sch 出图为 PDF",
             {"sch": ".kicad_sch 路径", "out": "输出 .pdf"}, handler=_export_sch_pdf, aliases=("sch_pdf",)),
        Verb("export_pcb_svg", "把 PCB 指定层导出为 SVG 矢量图",
             {"pcb": ".kicad_pcb 路径", "out": "输出 .svg", "layers": "层清单(逗号分隔)"},
             handler=_export_pcb_svg, aliases=("svg",)),
        Verb("pcb_python", "无头执行任意 pcbnew Python 脚本(改 net/track、原生 DRC、DSN/SES 往返等)",
             {"script": "内联 pcbnew Python", "macro_path": "脚本文件路径"},
             handler=_pcb_python, aliases=("pcbnew", "script")),
    ],
)
_ADAPTER = SubprocessApiAdapter
