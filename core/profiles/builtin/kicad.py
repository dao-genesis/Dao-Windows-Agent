"""KiCad 画像（级别① · kicad-cli / pcbnew Python，无头）。

收编自 Dao-PCB-Design-Agent 路线B（pcb_brain / kicad_origin）。
KiCad 提供 kicad-cli 与 pcbnew Python API，全流程无需 GUI → 天然隔离并行。
"""
from __future__ import annotations

from core.adapter.subprocess_api import SubprocessApiAdapter
from core.profiles.schema import AppProfile, AutomationLevel, Verb


def _version(adapter, instance, **_):
    return adapter.run_cli(["kicad-cli", "version"], instance)


def _export_gerbers(adapter, instance, pcb: str, out_dir: str = "gerbers", **_):
    return adapter.run_cli(["kicad-cli", "pcb", "export", "gerbers", "-o", out_dir, pcb], instance)


def _export_step(adapter, instance, pcb: str, out: str = "board.step", **_):
    return adapter.run_cli(["kicad-cli", "pcb", "export", "step", "-o", out, pcb], instance)


def _run_drc(adapter, instance, pcb: str, out: str = "drc.rpt", **_):
    return adapter.run_cli(["kicad-cli", "pcb", "drc", "-o", out, pcb], instance)


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
        Verb("export_step", "导出板子 3D STEP 模型",
             {"pcb": ".kicad_pcb 路径", "out": "输出 .step"}, handler=_export_step),
        Verb("run_drc", "运行设计规则检查(DRC)",
             {"pcb": ".kicad_pcb 路径", "out": "报告路径"}, handler=_run_drc, aliases=("drc",)),
    ],
)
_ADAPTER = SubprocessApiAdapter
