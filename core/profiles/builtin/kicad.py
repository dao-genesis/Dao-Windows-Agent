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
    ],
)
_ADAPTER = SubprocessApiAdapter
