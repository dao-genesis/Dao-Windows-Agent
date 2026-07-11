"""DAO 工具目录 — 把 FreeCAD 全量底层能力 1:1 工具化 (对照 Devin Desktop 工具设计)。

Devin Desktop / Windsurf / Cursor 之所以能让模型精准驱动 IDE，关键不在于工具*多*，
而在于每个工具都有**三件套**：唯一名字、一句"何时用"的描述、一份 JSON-Schema 参数契约。
本模块就是给引擎里已注册的每一个 op（``solid.box`` / ``param.pad`` / ``asm.solve`` …）
补齐这三件套，让 AI 副驾像调用 Devin Desktop 的 ``shell`` / ``str_replace`` 一样
调用 FreeCAD 的 ``solid.box``。

设计要点（道法自然 · 软编码）：

* **不硬编码工具清单**：以引擎运行时 ``eng.ops()`` 为准，本目录只提供"描述 + 参数模式"的
  *叠加层*。引擎新增 op 立即出现在工具面，未收录者自动按名字降级生成一条可用描述。
* **纯 Python、零 FreeCAD 依赖**：可在无内核环境下单测，也可被桥接/MCP/面板任意前端复用。
* **分类即导航**：14 组能力（solid/param/asm/measure/percept/mesh/draw/gui/doc/project/
  resource/analyze/ss/view）各带一句组说明，前端据此像 Devin Desktop 一样分栏罗列。
"""
from __future__ import annotations

from typing import Any, Dict, List

# --------------------------------------------------------------------------- #
# 组说明 (category → 何时用这一组)
# --------------------------------------------------------------------------- #
CATEGORIES: Dict[str, Dict[str, str]] = {
    "solid": {"title": "实体建模 Solid/BREP",
              "desc": "直接造几何：基本体、布尔、圆角倒角、阵列、齿轮机构、工程分析。"},
    "param": {"title": "参数化 PartDesign",
              "desc": "草图驱动的特征树：草图→凸台/凹槽/旋转/放样/扫掠，可回溯编辑。"},
    "asm": {"title": "装配 Assembly",
            "desc": "装入零件、约束对齐/同轴、求解、干涉检查、BOM 明细。"},
    "measure": {"title": "测量 Measure",
                "desc": "长度/角度/面积/体积/半径/质心/间距 — 声明 done 前先量。"},
    "percept": {"title": "感知 Percept",
                "desc": "把整个模型当源文件读：拓扑/特征/关系/剖面/差异，AI 的眼睛。"},
    "mesh": {"title": "网格 Mesh",
             "desc": "BREP↔网格互转、修复、抽取、布尔、导入导出 STL/OBJ。"},
    "draw": {"title": "工程图 TechDraw",
             "desc": "由 3D 投影生成二维工程图/视图。"},
    "gui": {"title": "视口感知 GUI",
            "desc": "活动文档的实时视口：截图/场景/选择/报错/视角 — 在 GUI 内才有。"},
    "doc": {"title": "文档 Document",
            "desc": "保存/信息/属性编辑/文档间差异 — 把 .FCStd 当可编辑对象。"},
    "project": {"title": "工程状态 Project",
                "desc": "工程级快照/差异/健康自检/简报 — 闭环验证的骨架。"},
    "resource": {"title": "天下资源 Resource",
                 "desc": "全网 3D 模型库检索/下载 (Printables/Sketchfab/NASA/GitHub) — 造之前先搜。"},
    "analyze": {"title": "分析 Analyze",
                "desc": "包围盒/最短距离/剖面等快速几何分析。"},
    "ss": {"title": "参数表 Spreadsheet",
           "desc": "电子表格驱动参数：建表/绑定/取值，一处改处处变。"},
    "view": {"title": "渲染视图 View",
             "desc": "触发场景刷新/离屏渲染/多视角。"},
}

# --------------------------------------------------------------------------- #
# 参数模式片段 (复用)
# --------------------------------------------------------------------------- #
_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}


def _schema(props: Dict[str, Any], required: List[str] | None = None) -> Dict[str, Any]:
    s: Dict[str, Any] = {"type": "object", "properties": props}
    if required:
        s["required"] = required
    return s


# --------------------------------------------------------------------------- #
# 精选工具契约 (name → {desc, params})
#   覆盖高频建模/装配/测量/感知 op；未收录者由 _fallback 自动降级生成。
# --------------------------------------------------------------------------- #
_CURATED: Dict[str, Dict[str, Any]] = {
    # ── solid.* 基本体 ────────────────────────────────────────────────
    "solid.box": {"desc": "造长方体。length/width/height 为 X/Y/Z 尺寸(mm)，可选放置点。",
                  "params": _schema({"name": _STR, "length": _NUM, "width": _NUM,
                                     "height": _NUM, "x": _NUM, "y": _NUM, "z": _NUM},
                                    ["length", "width", "height"])},
    "solid.cylinder": {"desc": "造圆柱。radius 半径、height 高(mm)。",
                       "params": _schema({"name": _STR, "radius": _NUM, "height": _NUM,
                                         "x": _NUM, "y": _NUM, "z": _NUM},
                                        ["radius", "height"])},
    "solid.sphere": {"desc": "造球。radius 半径(mm)。",
                     "params": _schema({"name": _STR, "radius": _NUM,
                                       "x": _NUM, "y": _NUM, "z": _NUM}, ["radius"])},
    "solid.cone": {"desc": "造圆锥/圆台。radius1 底半径、radius2 顶半径、height 高(mm)。",
                   "params": _schema({"name": _STR, "radius1": _NUM, "radius2": _NUM,
                                     "height": _NUM}, ["radius1", "height"])},
    "solid.torus": {"desc": "造圆环。radius1 主半径、radius2 管半径(mm)。",
                    "params": _schema({"name": _STR, "radius1": _NUM, "radius2": _NUM},
                                     ["radius1", "radius2"])},
    # ── solid.* 布尔与修饰 ───────────────────────────────────────────
    "solid.union": {"desc": "布尔并集(融合)。objects 为要合并的对象名列表。",
                    "params": _schema({"name": _STR, "objects": {"type": "array", "items": _STR}},
                                     ["objects"])},
    "solid.cut": {"desc": "布尔差集：从 base 减去 tool。",
                  "params": _schema({"name": _STR, "base": _STR, "tool": _STR},
                                   ["base", "tool"])},
    "solid.common": {"desc": "布尔交集：objects 的公共体。",
                     "params": _schema({"name": _STR, "objects": {"type": "array", "items": _STR}},
                                      ["objects"])},
    "solid.fillet": {"desc": "对对象所有(或指定)边倒圆角。radius 半径(mm)。",
                     "params": _schema({"object": _STR, "radius": _NUM,
                                       "edges": {"type": "array", "items": _INT}},
                                      ["object", "radius"])},
    "solid.chamfer": {"desc": "对边倒斜角。size 尺寸(mm)。",
                      "params": _schema({"object": _STR, "size": _NUM,
                                        "edges": {"type": "array", "items": _INT}},
                                       ["object", "size"])},
    "solid.shell": {"desc": "抽壳成薄壁。thickness 壁厚(mm)，faces 移除的面。",
                    "params": _schema({"object": _STR, "thickness": _NUM,
                                      "faces": {"type": "array", "items": _INT}},
                                     ["object", "thickness"])},
    "solid.translate": {"desc": "平移对象。dx/dy/dz 位移(mm)。",
                        "params": _schema({"object": _STR, "dx": _NUM, "dy": _NUM, "dz": _NUM},
                                         ["object"])},
    "solid.rotate": {"desc": "绕轴旋转对象。angle 角度(度)，axis 为 [x,y,z]。",
                     "params": _schema({"object": _STR, "angle": _NUM,
                                       "axis": {"type": "array", "items": _NUM}},
                                      ["object", "angle"])},
    "solid.mirror": {"desc": "镜像对象。plane 如 'XY'/'YZ'/'XZ'。",
                     "params": _schema({"object": _STR, "plane": _STR}, ["object"])},
    "solid.pattern_linear": {"desc": "线性阵列。count 数量、spacing 间距(mm)、direction 方向。",
                             "params": _schema({"object": _STR, "count": _INT, "spacing": _NUM,
                                               "direction": {"type": "array", "items": _NUM}},
                                              ["object", "count", "spacing"])},
    "solid.pattern_polar": {"desc": "环形阵列。count 数量、angle 总角(度)、axis 轴。",
                            "params": _schema({"object": _STR, "count": _INT, "angle": _NUM},
                                             ["object", "count"])},
    "solid.extrude": {"desc": "拉伸截面成体。length 拉伸长度(mm)。",
                      "params": _schema({"object": _STR, "length": _NUM}, ["object", "length"])},
    "solid.revolve": {"desc": "截面绕轴旋转成体。angle 角度(度)。",
                      "params": _schema({"object": _STR, "angle": _NUM}, ["object"])},
    "solid.export": {"desc": "导出对象为 STEP/STL/IGES/BREP。path 目标文件路径。",
                     "params": _schema({"objects": {"type": "array", "items": _STR}, "path": _STR},
                                      ["path"])},
    "solid.import_step": {"desc": "导入 STEP/IGES 文件为对象。path 源文件。",
                          "params": _schema({"path": _STR}, ["path"])},
    "solid.list": {"desc": "列出当前文档所有实体对象及其类型。",
                   "params": _schema({})},
    "solid.measure": {"desc": "量对象的体积/面积/包围盒/质心。",
                      "params": _schema({"object": _STR}, ["object"])},
    "solid.interference": {"desc": "检查两组对象间的干涉/碰撞体积。",
                           "params": _schema({"objects": {"type": "array", "items": _STR}})},
    "solid.inertia": {"desc": "计算质量/质心/惯性张量。density 密度(kg/m^3)。",
                      "params": _schema({"object": _STR, "density": _NUM}, ["object"])},
    "solid.gearmesh": {"desc": "生成一对啮合渐开线齿轮。module 模数、z1/z2 齿数。",
                       "params": _schema({"module": _NUM, "z1": _INT, "z2": _INT},
                                        ["module", "z1", "z2"])},
    "solid.geartrain": {"desc": "生成齿轮传动系。stages 各级齿数比。",
                        "params": _schema({"stages": {"type": "array"}})},
    # ── param.* 参数化特征 ───────────────────────────────────────────
    "param.body": {"desc": "新建 PartDesign Body(参数化特征树的容器)。",
                   "params": _schema({"name": _STR})},
    "param.sketch": {"desc": "在指定基准面上建草图。plane 'XY'/'XZ'/'YZ'，geometry 几何列表。",
                     "params": _schema({"body": _STR, "plane": _STR, "geometry": {"type": "array"}})},
    "param.pad": {"desc": "把草图凸台拉伸。length 拉伸长度(mm)。",
                  "params": _schema({"sketch": _STR, "length": _NUM}, ["length"])},
    "param.pocket": {"desc": "把草图凹槽切除。length 深度(mm)。",
                     "params": _schema({"sketch": _STR, "length": _NUM}, ["length"])},
    "param.revolve": {"desc": "草图绕轴旋转成体。angle 角度(度)。",
                      "params": _schema({"sketch": _STR, "angle": _NUM})},
    "param.fillet": {"desc": "参数化圆角(特征树内，可回溯)。radius 半径(mm)。",
                     "params": _schema({"body": _STR, "radius": _NUM,
                                       "edges": {"type": "array", "items": _INT}}, ["radius"])},
    "param.chamfer": {"desc": "参数化倒角。size 尺寸(mm)。",
                      "params": _schema({"body": _STR, "size": _NUM}, ["size"])},
    "param.pattern_linear": {"desc": "特征线性阵列。count/spacing。",
                             "params": _schema({"feature": _STR, "count": _INT, "spacing": _NUM})},
    "param.pattern_polar": {"desc": "特征环形阵列。count/angle。",
                            "params": _schema({"feature": _STR, "count": _INT, "angle": _NUM})},
    "param.set": {"desc": "设置/修改特征或草图的参数值(参数化编辑)。",
                  "params": _schema({"object": _STR, "property": _STR, "value": {}})},
    "param.tree": {"desc": "列出参数化特征树结构。", "params": _schema({})},
    "param.diagnose": {"desc": "诊断特征树的报错/失效特征。", "params": _schema({})},
    # ── asm.* 装配 ──────────────────────────────────────────────────
    "asm.create": {"desc": "新建装配体容器。", "params": _schema({"name": _STR})},
    "asm.add": {"desc": "把零件装入装配。object 零件名，可给初始位姿。",
                "params": _schema({"object": _STR, "x": _NUM, "y": _NUM, "z": _NUM}, ["object"])},
    "asm.align": {"desc": "添加对齐约束(面/边/点)。",
                  "params": _schema({"a": _STR, "b": _STR, "type": _STR})},
    "asm.coaxial": {"desc": "添加同轴约束(两圆柱/孔共轴)。",
                    "params": _schema({"a": _STR, "b": _STR})},
    "asm.solve": {"desc": "求解装配约束，把零件移到满足约束的位姿。", "params": _schema({})},
    "asm.interference": {"desc": "全装配干涉检查，列出相交零件对与体积。", "params": _schema({})},
    "asm.bom": {"desc": "生成物料清单(BOM)：零件、数量、材料。", "params": _schema({})},
    "asm.tree": {"desc": "列出装配层级树。", "params": _schema({})},
    "asm.move": {"desc": "平移某装配零件。dx/dy/dz(mm)。",
                 "params": _schema({"object": _STR, "dx": _NUM, "dy": _NUM, "dz": _NUM}, ["object"])},
    "asm.rotate": {"desc": "旋转某装配零件。angle(度)、axis。",
                   "params": _schema({"object": _STR, "angle": _NUM}, ["object"])},
    "asm.export": {"desc": "导出整个装配为 STEP。path 目标。",
                   "params": _schema({"path": _STR}, ["path"])},
    # ── measure.* 测量 ──────────────────────────────────────────────
    "measure.length": {"desc": "量边/曲线长度(mm)。", "params": _schema({"object": _STR, "edge": _INT})},
    "measure.area": {"desc": "量面/对象表面积(mm^2)。", "params": _schema({"object": _STR})},
    "measure.volume": {"desc": "量实体体积(mm^3)。", "params": _schema({"object": _STR})},
    "measure.angle": {"desc": "量两边/两面夹角(度)。", "params": _schema({"a": _STR, "b": _STR})},
    "measure.radius": {"desc": "量圆/圆弧/圆柱半径(mm)。", "params": _schema({"object": _STR})},
    "measure.com": {"desc": "量质心坐标。", "params": _schema({"object": _STR})},
    "measure.delta": {"desc": "量两对象间的距离向量。", "params": _schema({"a": _STR, "b": _STR})},
    # ── percept.* 感知 ──────────────────────────────────────────────
    "percept.scene": {"desc": "读整个场景结构：对象、类型、层级 — 建模前先看。", "params": _schema({})},
    "percept.topology": {"desc": "读某对象拓扑：面/边/顶点计数与索引。", "params": _schema({"object": _STR})},
    "percept.features": {"desc": "识别对象上的特征(孔/圆角/凸台等)。", "params": _schema({"object": _STR})},
    "percept.relations": {"desc": "分析对象间的空间关系(接触/同轴/包含)。", "params": _schema({})},
    "percept.describe": {"desc": "用自然语言描述当前模型全貌。", "params": _schema({})},
    "percept.diff": {"desc": "对比两次快照的差异。", "params": _schema({"base": _STR})},
    # ── project.* 工程状态 ──────────────────────────────────────────
    "project.state": {"desc": "工程健康自检：列出失效/报错/未定义的对象。声明 done 前必看。",
                      "params": _schema({"features": _BOOL})},
    "project.snapshot": {"desc": "给当前工程打快照(供事后 diff)。label 标签。",
                        "params": _schema({"label": _STR}, ["label"])},
    "project.diff": {"desc": "把当前工程与某快照对比，列出增删改。",
                    "params": _schema({"base": _STR}, ["base"])},
    "project.brief": {"desc": "读工程简报(设计意图/约束)。", "params": _schema({})},
    # ── mesh.* 网格 ─────────────────────────────────────────────────
    "mesh.from_shape": {"desc": "把 BREP 实体三角化为网格。", "params": _schema({"object": _STR})},
    "mesh.to_shape": {"desc": "把网格重建为 BREP 实体。", "params": _schema({"object": _STR})},
    "mesh.export": {"desc": "导出网格为 STL/OBJ/PLY。path 目标。",
                    "params": _schema({"object": _STR, "path": _STR}, ["path"])},
    "mesh.import": {"desc": "导入 STL/OBJ 网格文件。path 源。", "params": _schema({"path": _STR}, ["path"])},
    "mesh.repair": {"desc": "修复网格(补洞/去重/翻面)。", "params": _schema({"object": _STR})},
    "mesh.decimate": {"desc": "抽取简化网格。ratio 保留比例(0-1)。", "params": _schema({"object": _STR, "ratio": _NUM})},
    # ── gui.* 视口 ──────────────────────────────────────────────────
    "gui.snapshot": {"desc": "截取活动视口为图片。path 保存路径(可选)。", "params": _schema({"path": _STR, "view": _STR})},
    "gui.scene": {"desc": "读视口内可见对象的结构化场景。", "params": _schema({})},
    "gui.selection": {"desc": "读当前在 GUI 中选中的对象。", "params": _schema({})},
    "gui.perceive": {"desc": "一次调用拿到 场景+截图+选择+报错(复合感知)。", "params": _schema({})},
    "gui.fit": {"desc": "视口适合全部对象。", "params": _schema({})},
    "gui.view": {"desc": "切换标准视角(iso/front/top/right…)。", "params": _schema({"view": _STR})},
    # ── doc.* 文档 ──────────────────────────────────────────────────
    "doc.save": {"desc": "保存文档到磁盘。path 目标 .FCStd。", "params": _schema({"path": _STR}, ["path"])},
    "doc.info": {"desc": "文档信息：名称与全部对象。", "params": _schema({})},
    "doc.inspect": {"desc": "把某 .FCStd 当源文件解析出可读结构。", "params": _schema({"path": _STR}, ["path"])},
    "doc.edit": {"desc": "直接编辑某对象属性(离文档编辑)。",
                 "params": _schema({"path": _STR, "object": _STR, "property": _STR, "value": {}})},
    # ── resource.* 天下资源 ─────────────────────────────────────────
    "resource.search": {"desc": "全网并行检索 3D 模型库(Printables/Sketchfab/NASA/GitHub)。造之前先搜现成件。",
                        "params": _schema({"query": _STR, "platforms": {"type": "array", "items": _STR},
                                          "limit": _INT}, ["query"])},
    "resource.platforms": {"desc": "列出可检索的资源平台。", "params": _schema({})},
    "resource.download": {"desc": "下载某检索结果的模型文件。", "params": _schema({"url": _STR, "dest": _STR})},
}


# --------------------------------------------------------------------------- #
# 自动降级：为未收录 op 依据命名习惯生成一条可用描述
# --------------------------------------------------------------------------- #
_VERB_HINT = {
    "list": "列出", "tree": "列出树结构", "info": "读取信息", "diagnose": "诊断",
    "measure": "测量", "export": "导出", "import": "导入", "section": "剖切",
    "recognize": "识别", "inspect": "检查", "report": "生成报告", "analyze": "分析",
    "solve": "求解", "match": "匹配", "reverse": "逆向重建",
}


def _fallback(op: str) -> Dict[str, Any]:
    grp, _, verb = op.partition(".")
    cat = CATEGORIES.get(grp, {})
    hint = _VERB_HINT.get(verb, "")
    human = verb.replace("_", " ")
    desc = "%s%s (%s)" % (hint, human, cat.get("title", grp)) if hint else \
           "%s — %s" % (human, cat.get("desc", grp))
    return {"desc": desc, "params": _schema({})}


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def spec_for(op: str) -> Dict[str, Any]:
    """返回单个 op 的 Devin-Desktop 式契约 {name, category, description, parameters}."""
    grp = op.split(".", 1)[0]
    base = _CURATED.get(op) or _fallback(op)
    return {"name": op, "category": grp,
            "description": base["desc"], "parameters": base.get("params", _schema({}))}


def build_catalog(ops: List[str]) -> Dict[str, Any]:
    """按引擎运行时 op 列表生成完整工具目录(分组 + 计数 + 覆盖率)."""
    groups: Dict[str, Dict[str, Any]] = {}
    curated = 0
    for op in sorted(ops):
        grp = op.split(".", 1)[0]
        g = groups.setdefault(grp, {**CATEGORIES.get(grp, {"title": grp, "desc": ""}),
                                     "group": grp, "tools": []})
        g["tools"].append(spec_for(op))
        if op in _CURATED:
            curated += 1
    return {"count": len(ops), "curated": curated,
            "groups": [groups[k] for k in sorted(groups)]}


def prompt_block(ops: List[str], max_per_group: int | None = None) -> str:
    """为 LLM 系统提示词生成富工具清单(名字 + 描述 + 必填参数)。

    对照 Devin Desktop：模型不是靠工具名猜用途，而是读描述与参数契约来精确调用。
    """
    cat = build_catalog(ops)
    lines: List[str] = []
    for g in cat["groups"]:
        lines.append("## %s (%s.*) — %s" % (g["title"], g["group"], g.get("desc", "")))
        tools = g["tools"][:max_per_group] if max_per_group else g["tools"]
        for t in tools:
            req = t["parameters"].get("required") or []
            props = t["parameters"].get("properties") or {}
            arg = ""
            if props:
                shown = ", ".join(
                    ("%s*" % k if k in req else k) for k in list(props)[:8])
                arg = "  {%s}" % shown
            lines.append("- `%s` — %s%s" % (t["name"], t["description"], arg))
        if max_per_group and len(g["tools"]) > max_per_group:
            lines.append("  … 及 %d 个同组工具" % (len(g["tools"]) - max_per_group))
    return "\n".join(lines)
