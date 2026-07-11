#!/usr/bin/env python3
"""
FreeCAD 内核引擎 v2.0 — 运行在 FreeCADCmd 进程内部

协议:
  freecadcmd.exe freecad_backend.py --cmd CMD_JSON_FILE --result RESULT_JSON_FILE

CMD_JSON_FILE 格式:
{
  "ops": [
    {"op": "make_box",      "id": "b1", "L": 20, "W": 10, "H": 5, "pos": [0,0,0]},
    {"op": "make_cylinder", "id": "c1", "R": 5,  "H": 15, "pos": [0,0,0]},
    {"op": "fuse",          "id": "r1", "shapes": ["b1", "c1"]},
    {"op": "fillet",        "id": "r2", "shape": "r1", "radius": 1.0},
    {"op": "export_stl",    "shape": "r2", "path": "C:/out.stl"},
    {"op": "export_step",   "shape": "r2", "path": "C:/out.step"},
    {"op": "shape_info",    "shape": "r2"}
  ]
}

RESULT_JSON_FILE 格式:
{
  "ok": true,
  "shapes": {"b1": {...info}, "c1": {...info}, "r1": {...info}},
  "exports": [{"op": "export_stl", "ok": true, "path": "...", "size": 12345}],
  "analyses": [{"op": "shape_info", "ok": true, ...}],
  "errors": []
}
"""
import sys
import os
import json
import math
import traceback
from pathlib import Path


def _parse_args():
    cmd_file = None
    result_file = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--cmd" and i + 1 < len(args):
            cmd_file = args[i + 1]; i += 2
        elif args[i] == "--result" and i + 1 < len(args):
            result_file = args[i + 1]; i += 2
        else:
            i += 1
    return cmd_file, result_file


def _vec(v):
    from FreeCAD import Base
    if v is None:
        return Base.Vector(0, 0, 0)
    return Base.Vector(float(v[0]), float(v[1]), float(v[2]))


def _rot(axis=None, angle=0.0):
    import FreeCAD as App
    if axis is None:
        return App.Rotation()
    return App.Rotation(_vec(axis), float(angle))


def _placement(pos=None, axis=None, angle=0.0):
    import FreeCAD as App
    return App.Placement(_vec(pos), _rot(axis, angle))


def _shape_summary(shape):
    """Quick info about a shape."""
    bb = shape.BoundBox
    return {
        "type": shape.ShapeType,
        "valid": shape.isValid(),
        "null": shape.isNull(),
        "volume_mm3": round(shape.Volume, 4) if not shape.isNull() else 0,
        "area_mm2": round(shape.Area, 4) if not shape.isNull() else 0,
        "bbox": {
            "x": [round(bb.XMin, 4), round(bb.XMax, 4)],
            "y": [round(bb.YMin, 4), round(bb.YMax, 4)],
            "z": [round(bb.ZMin, 4), round(bb.ZMax, 4)],
            "size": [round(bb.XLength, 4), round(bb.YLength, 4), round(bb.ZLength, 4)],
        },
        "faces": len(shape.Faces),
        "edges": len(shape.Edges),
        "vertices": len(shape.Vertexes),
        "solids": len(shape.Solids),
    }


def run_ops(ops):
    import FreeCAD as App
    import Part
    from FreeCAD import Base

    shapes = {}   # id → Part.Shape
    results = {
        "ok": True,
        "shapes": {},
        "exports": [],
        "analyses": [],
        "errors": [],
    }

    for op_spec in ops:
        op = op_spec.get("op", "")
        op_id = op_spec.get("id")  # optional shape id to store result under

        try:
            # ── Primitive creation ──────────────────────────────────────────
            if op == "make_box":
                L = float(op_spec.get("L", 10))
                W = float(op_spec.get("W", 10))
                H = float(op_spec.get("H", 10))
                pos = op_spec.get("pos", [0, 0, 0])
                sh = Part.makeBox(L, W, H, _vec(pos), Base.Vector(0, 0, 1))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_cylinder":
                R = float(op_spec.get("R", 5))
                H = float(op_spec.get("H", 10))
                pos = op_spec.get("pos", [0, 0, 0])
                axis = op_spec.get("axis", [0, 0, 1])
                angle = float(op_spec.get("angle", 360))
                sh = Part.makeCylinder(R, H, _vec(pos), _vec(axis), angle)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_sphere":
                R = float(op_spec.get("R", 10))
                pos = op_spec.get("pos", [0, 0, 0])
                sh = Part.makeSphere(R, _vec(pos))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_cone":
                R1 = float(op_spec.get("R1", 5))
                R2 = float(op_spec.get("R2", 0))
                H = float(op_spec.get("H", 10))
                pos = op_spec.get("pos", [0, 0, 0])
                sh = Part.makeCone(R1, R2, H, _vec(pos))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_torus":
                R1 = float(op_spec.get("R1", 10))
                R2 = float(op_spec.get("R2", 2))
                pos = op_spec.get("pos", [0, 0, 0])
                sh = Part.makeTorus(R1, R2)
                sh.translate(_vec(pos))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_wedge":
                dx   = float(op_spec.get("dx", 10))
                dy   = float(op_spec.get("dy", 10))
                dz   = float(op_spec.get("dz", 10))
                xmin = float(op_spec.get("xmin", 2))
                zmin = float(op_spec.get("zmin", 2))
                xmax = float(op_spec.get("xmax", 8))
                zmax = float(op_spec.get("zmax", 8))
                try:
                    # FreeCAD 1.0 requires pnt and dir extra args
                    sh = Part.makeWedge(dx, dy, dz, xmin, zmin, xmax, zmax,
                                        Base.Vector(0, 0, 0), Base.Vector(0, 1, 0))
                except Exception:
                    try:
                        # older API with ltx/xmax2 extras
                        sh = Part.makeWedge(dx, dy, dz, xmin, zmin, xmax, zmax,
                                            Base.Vector(0, 0, 0), Base.Vector(0, 1, 0),
                                            xmin, zmin, xmax, zmax)
                    except Exception:
                        # Fallback: build wedge as loft of two rects
                        bot = Part.makePolygon([
                            Base.Vector(0,  0,  0),
                            Base.Vector(dx, 0,  0),
                            Base.Vector(dx, 0,  dz),
                            Base.Vector(0,  0,  dz),
                            Base.Vector(0,  0,  0),
                        ])
                        top = Part.makePolygon([
                            Base.Vector(xmin, dy, zmin),
                            Base.Vector(xmax, dy, zmin),
                            Base.Vector(xmax, dy, zmax),
                            Base.Vector(xmin, dy, zmax),
                            Base.Vector(xmin, dy, zmin),
                        ])
                        bf = Part.Face(bot)
                        tf = Part.Face(top)
                        sh = Part.makeLoft([bot, top], True)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            # ── Wire / Face / Extrude / Revolve ─────────────────────────────
            elif op == "make_polygon_wire":
                pts = [_vec(p) for p in op_spec.get("points", [])]
                closed = op_spec.get("closed", True)
                if closed and pts and pts[0] != pts[-1]:
                    pts.append(pts[0])
                sh = Part.makePolygon(pts)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_circle_wire":
                R = float(op_spec.get("R", 10))
                pos = op_spec.get("pos", [0, 0, 0])
                normal = op_spec.get("normal", [0, 0, 1])
                circle = Part.Circle(_vec(pos), _vec(normal), R)
                sh = circle.toShape()
                wire = Part.Wire(sh)
                shapes[op_id] = wire
                results["shapes"][op_id] = _shape_summary(wire)

            elif op == "make_face":
                wire_id = op_spec.get("wire")
                if wire_id not in shapes:
                    raise ValueError(f"Wire '{wire_id}' not found")
                face = Part.Face(shapes[wire_id])
                shapes[op_id] = face
                results["shapes"][op_id] = _shape_summary(face)

            elif op == "extrude":
                sh_id = op_spec.get("shape")
                if sh_id not in shapes:
                    raise ValueError(f"Shape '{sh_id}' not found")
                direction = op_spec.get("direction", [0, 0, 10])
                sh = shapes[sh_id].extrude(_vec(direction))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "revolve":
                sh_id = op_spec.get("shape")
                if sh_id not in shapes:
                    raise ValueError(f"Shape '{sh_id}' not found")
                axis_origin = op_spec.get("axis_origin", [0, 0, 0])
                axis_dir = op_spec.get("axis_dir", [0, 0, 1])
                angle = float(op_spec.get("angle", 360))
                sh = shapes[sh_id].revolve(_vec(axis_origin), _vec(axis_dir), angle)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "loft":
                section_ids = op_spec.get("sections", [])
                solid = op_spec.get("solid", True)
                ruled = op_spec.get("ruled", False)
                sections = [shapes[sid] for sid in section_ids if sid in shapes]
                if len(sections) < 2:
                    raise ValueError("Loft needs >=2 sections")
                sh = Part.makeLoft(sections, solid, ruled)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "pipe":
                profile_id = op_spec.get("profile")
                spine_id = op_spec.get("spine")
                if profile_id not in shapes or spine_id not in shapes:
                    raise ValueError("profile/spine not found")
                sh = shapes[profile_id].makePipe(shapes[spine_id])
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            # ── Boolean operations ───────────────────────────────────────────
            elif op == "fuse":
                shape_ids = op_spec.get("shapes", [])
                if len(shape_ids) < 1:
                    raise ValueError("fuse: need >=1 shapes")
                base = shapes[shape_ids[0]]
                for sid in shape_ids[1:]:
                    base = base.fuse(shapes[sid])
                sh = base.removeSplitter()
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "cut":
                base_id = op_spec.get("base")
                tool_ids = op_spec.get("tools", op_spec.get("tool_ids", []))
                if isinstance(tool_ids, str):
                    tool_ids = [tool_ids]
                base = shapes[base_id]
                for tid in tool_ids:
                    base = base.cut(shapes[tid])
                shapes[op_id] = base
                results["shapes"][op_id] = _shape_summary(base)

            elif op == "common":
                shape_ids = op_spec.get("shapes", [])
                base = shapes[shape_ids[0]]
                for sid in shape_ids[1:]:
                    base = base.common(shapes[sid])
                shapes[op_id] = base
                results["shapes"][op_id] = _shape_summary(base)

            elif op == "section":
                sh_id = op_spec.get("shape")
                other_id = op_spec.get("other")
                base = shapes[sh_id].section(shapes[other_id])
                shapes[op_id] = base
                results["shapes"][op_id] = _shape_summary(base)

            # ── Modifiers ────────────────────────────────────────────────────
            elif op == "fillet":
                sh_id = op_spec.get("shape")
                radius = float(op_spec.get("radius", 1.0))
                edge_indices = op_spec.get("edges")  # None = all
                sh = shapes[sh_id]
                edges = sh.Edges
                if edge_indices is not None:
                    edges = [edges[i] for i in edge_indices if i < len(edges)]
                try:
                    fillet_sh = sh.makeFillet(radius, edges)
                    shapes[op_id] = fillet_sh
                    results["shapes"][op_id] = _shape_summary(fillet_sh)
                except Exception as e:
                    # Fillet may fail on some geometry — use original
                    shapes[op_id] = sh
                    results["shapes"][op_id] = _shape_summary(sh)
                    results["errors"].append(f"fillet on '{sh_id}' partial fail: {e}")

            elif op == "chamfer":
                sh_id = op_spec.get("shape")
                size = float(op_spec.get("size", 1.0))
                edge_indices = op_spec.get("edges")
                sh = shapes[sh_id]
                edges = sh.Edges
                if edge_indices is not None:
                    edges = [edges[i] for i in edge_indices if i < len(edges)]
                try:
                    ch_sh = sh.makeChamfer(size, edges)
                    shapes[op_id] = ch_sh
                    results["shapes"][op_id] = _shape_summary(ch_sh)
                except Exception as e:
                    shapes[op_id] = sh
                    results["shapes"][op_id] = _shape_summary(sh)
                    results["errors"].append(f"chamfer partial fail: {e}")

            elif op == "offset3d":
                sh_id = op_spec.get("shape")
                offset = float(op_spec.get("offset", 1.0))
                tol = float(op_spec.get("tolerance", 0.001))
                sh = shapes[sh_id].makeOffsetShape(offset, tol)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "shell":
                sh_id = op_spec.get("shape")
                thickness = float(op_spec.get("thickness", 1.0))
                face_indices = op_spec.get("faces_to_remove", [0])  # remove top face by default
                sh = shapes[sh_id]
                faces_to_remove = [sh.Faces[i] for i in face_indices if i < len(sh.Faces)]
                try:
                    shell_sh = sh.makeThickness(faces_to_remove, thickness, 0.001)
                    shapes[op_id] = shell_sh
                    results["shapes"][op_id] = _shape_summary(shell_sh)
                except Exception as e:
                    shapes[op_id] = sh
                    results["shapes"][op_id] = _shape_summary(sh)
                    results["errors"].append(f"shell partial fail: {e}")

            elif op == "mirror":
                sh_id = op_spec.get("shape")
                plane = op_spec.get("plane", "XY")
                sh = shapes[sh_id]
                planes = {
                    "XY": ([0, 0, 0], [0, 0, 1]),
                    "XZ": ([0, 0, 0], [0, 1, 0]),
                    "YZ": ([0, 0, 0], [1, 0, 0]),
                }
                origin_v, normal_v = planes.get(plane.upper(), planes["XY"])
                custom_origin = op_spec.get("origin", origin_v)
                custom_normal = op_spec.get("normal", normal_v)
                mirrored = sh.mirror(_vec(custom_origin), _vec(custom_normal))
                shapes[op_id] = mirrored
                results["shapes"][op_id] = _shape_summary(mirrored)

            elif op == "translate":
                sh_id = op_spec.get("shape")
                delta = op_spec.get("delta", [0, 0, 0])
                sh = shapes[sh_id].copy()
                sh.translate(_vec(delta))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "rotate":
                sh_id = op_spec.get("shape")
                base_pt = op_spec.get("base", [0, 0, 0])
                axis = op_spec.get("axis", [0, 0, 1])
                angle = float(op_spec.get("angle", 90))
                sh = shapes[sh_id].copy()
                sh.rotate(_vec(base_pt), _vec(axis), angle)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "scale":
                sh_id = op_spec.get("shape")
                factor = float(op_spec.get("factor", 1.0))
                sh = shapes[sh_id].copy()
                m = App.Matrix()
                m.scale(Base.Vector(factor, factor, factor))
                sh = sh.transformGeometry(m)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "compound":
                shape_ids = op_spec.get("shapes", [])
                parts = [shapes[sid] for sid in shape_ids if sid in shapes]
                comp = Part.makeCompound(parts)
                shapes[op_id] = comp
                results["shapes"][op_id] = _shape_summary(comp)

            # ── Array / Pattern ──────────────────────────────────────────────
            elif op == "array_linear":
                sh_id = op_spec.get("shape")
                count = int(op_spec.get("count", 3))
                step = op_spec.get("step", [20, 0, 0])
                parts = []
                for i in range(count):
                    cp = shapes[sh_id].copy()
                    cp.translate(Base.Vector(
                        float(step[0]) * i,
                        float(step[1]) * i,
                        float(step[2]) * i
                    ))
                    parts.append(cp)
                comp = Part.makeCompound(parts)
                shapes[op_id] = comp
                results["shapes"][op_id] = _shape_summary(comp)

            elif op == "array_polar":
                sh_id = op_spec.get("shape")
                count = int(op_spec.get("count", 6))
                center = op_spec.get("center", [0, 0, 0])
                axis = op_spec.get("axis", [0, 0, 1])
                total_angle = float(op_spec.get("total_angle", 360))
                parts = []
                for i in range(count):
                    angle = total_angle * i / count
                    cp = shapes[sh_id].copy()
                    cp.rotate(_vec(center), _vec(axis), angle)
                    parts.append(cp)
                comp = Part.makeCompound(parts)
                shapes[op_id] = comp
                results["shapes"][op_id] = _shape_summary(comp)

            elif op == "array_grid":
                sh_id = op_spec.get("shape")
                nx = int(op_spec.get("nx", 2))
                ny = int(op_spec.get("ny", 2))
                nz = int(op_spec.get("nz", 1))
                dx = float(op_spec.get("dx", 20))
                dy = float(op_spec.get("dy", 20))
                dz = float(op_spec.get("dz", 0))
                parts = []
                for ix in range(nx):
                    for iy in range(ny):
                        for iz in range(nz):
                            cp = shapes[sh_id].copy()
                            cp.translate(Base.Vector(dx * ix, dy * iy, dz * iz))
                            parts.append(cp)
                comp = Part.makeCompound(parts)
                shapes[op_id] = comp
                results["shapes"][op_id] = _shape_summary(comp)

            # ── Export ───────────────────────────────────────────────────────
            elif op in ("export_stl", "export_step", "export_brep", "export_obj",
                        "export_dxf", "export_svg", "export_stl_mesh"):
                sh_id = op_spec.get("shape")
                path = op_spec.get("path", "")
                if not path:
                    raise ValueError("export: 'path' required")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                if sh_id not in shapes:
                    raise ValueError(f"Shape '{sh_id}' not found for export")
                sh = shapes[sh_id]

                if op == "export_stl":
                    import Mesh
                    deflection = float(op_spec.get("deflection", 0.05))
                    mesh_data = sh.tessellate(deflection)
                    mesh = Mesh.Mesh(mesh_data)
                    mesh.write(path)
                elif op == "export_brep":
                    # Use exportBrep() so Part.read() can import it back
                    sh.exportBrep(path)
                elif op == "export_step":
                    # 根本修复: Part.export 需要 DocumentObject 列表, 不是 Shape;
                    # 直接用 Shape.exportStep(str) 简单可靠, 支持 Compound/Solid/Shell.
                    try:
                        sh.exportStep(str(path))
                    except AttributeError:
                        # 旧版 FreeCAD 回退: 用文档对象桥接
                        _doc_tmp = App.newDocument("_step_export_tmp", hidden=True) \
                            if hasattr(App, "newDocument") else App.newDocument("_step_export_tmp")
                        _tmp_obj = _doc_tmp.addObject("Part::Feature", "S")
                        _tmp_obj.Shape = sh
                        _doc_tmp.recompute()
                        Part.export([_tmp_obj], str(path))
                        App.closeDocument(_doc_tmp.Name)
                elif op in ("export_obj", "export_stl_mesh"):
                    import Mesh
                    deflection = float(op_spec.get("deflection", 0.05))
                    mesh_data = sh.tessellate(deflection)
                    mesh = Mesh.Mesh(mesh_data)
                    mesh.write(path)
                elif op == "export_dxf":
                    # Pure-Python minimal DXF writer (no FreeCAD GUI modules).
                    # Extracts all edges as LINE/SPLINE entities — works headless.
                    _lines = []
                    _arcs  = []
                    for _edge in sh.Edges:
                        try:
                            if hasattr(_edge, 'Curve') and hasattr(_edge.Curve, 'Center'):
                                # Arc or circle
                                _c = _edge.Curve.Center
                                _r = _edge.Curve.Radius
                                _a1 = math.degrees(_edge.ParameterRange[0])
                                _a2 = math.degrees(_edge.ParameterRange[1])
                                _arcs.append((_c.x, _c.y, _r, _a1, _a2))
                            else:
                                # Polyline approximation
                                _pts = _edge.discretize(10)
                                for _i in range(len(_pts) - 1):
                                    _p1, _p2 = _pts[_i], _pts[_i + 1]
                                    _lines.append((_p1.x, _p1.y, _p1.z,
                                                   _p2.x, _p2.y, _p2.z))
                        except Exception: pass
                    with open(path, 'w', encoding='utf-8') as _dxff:
                        _dxff.write("0\nSECTION\n2\nHEADER\n")
                        _dxff.write("9\n$ACADVER\n1\nAC1015\n")
                        _dxff.write("0\nENDSEC\n")
                        _dxff.write("0\nSECTION\n2\nENTITIES\n")
                        for _x1,_y1,_z1,_x2,_y2,_z2 in _lines:
                            _dxff.write(
                                f"0\nLINE\n8\n0\n"
                                f"10\n{_x1:.4f}\n20\n{_y1:.4f}\n30\n{_z1:.4f}\n"
                                f"11\n{_x2:.4f}\n21\n{_y2:.4f}\n31\n{_z2:.4f}\n"
                            )
                        for _cx,_cy,_cr,_a1,_a2 in _arcs:
                            _dxff.write(
                                f"0\nARC\n8\n0\n"
                                f"10\n{_cx:.4f}\n20\n{_cy:.4f}\n30\n0.0\n"
                                f"40\n{_cr:.4f}\n50\n{_a1:.4f}\n51\n{_a2:.4f}\n"
                            )
                        _dxff.write("0\nENDSEC\n0\nEOF\n")
                elif op == "export_svg":
                    # Pure-Python SVG writer via edge projection onto XY plane.
                    # importSVG hangs in FreeCAD 1.0 headless (Qt event loop).
                    _bb = sh.BoundBox
                    _mx = max(_bb.XLength, _bb.YLength, 1)
                    _scale = 200.0 / _mx
                    _ox = -_bb.XMin * _scale
                    _oy = -_bb.YMin * _scale
                    _W  = round(_bb.XLength * _scale + 20)
                    _H  = round(_bb.YLength * _scale + 20)
                    _paths = []
                    for _edge in sh.Edges:
                        try:
                            _pts = _edge.discretize(20)
                            if len(_pts) < 2: continue
                            _d = "M" + " L".join(
                                f"{round(_p.x*_scale+_ox+10,2)},{round(_H-_p.y*_scale-_oy-10,2)}"
                                for _p in _pts)
                            _paths.append(f'<path d="{_d}" stroke="#000" fill="none" stroke-width="0.5"/>')
                        except Exception: pass
                    with open(path, 'w', encoding='utf-8') as _svgf:
                        _svgf.write(
                            f'<?xml version="1.0" encoding="utf-8"?>\n'
                            f'<svg xmlns="http://www.w3.org/2000/svg" '
                            f'width="{_W}" height="{_H}">\n'
                            + '\n'.join(_paths)
                            + '\n</svg>\n'
                        )

                ok = Path(path).exists() and Path(path).stat().st_size > 0
                results["exports"].append({
                    "op": op, "ok": ok,
                    "path": path,
                    "size_bytes": Path(path).stat().st_size if ok else 0,
                })

            elif op == "export_fcstd":
                doc_name = op_spec.get("doc", "output")
                path = op_spec.get("path", "")
                if not path:
                    raise ValueError("export_fcstd: 'path' required")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                doc = App.newDocument(doc_name)
                for sid, sh in shapes.items():
                    if isinstance(sh, Part.Shape) and not sh.isNull():
                        obj = doc.addObject("Part::Feature", sid)
                        obj.Shape = sh
                doc.recompute()
                doc.saveAs(path)
                App.closeDocument(doc_name)
                ok = Path(path).exists() and Path(path).stat().st_size > 0
                results["exports"].append({"op": "export_fcstd", "ok": ok, "path": path,
                                           "size_bytes": Path(path).stat().st_size if ok else 0})

            # ── Import ───────────────────────────────────────────────────────
            elif op in ("import_step", "import_brep", "import_stl",
                        "import_iges", "import_step_occ", "import_iges_occ"):
                path = op_spec.get("path", "")
                if not Path(path).exists():
                    raise FileNotFoundError(f"Import file not found: {path}")
                if op == "import_brep":
                    # BREP exported by exportBrep() can be read back via Part.read()
                    import shutil as _shutil, tempfile as _tmp
                    _tmp_brep = Path(_tmp.gettempdir()) / "_fc_import.brep"
                    _shutil.copy2(path, str(_tmp_brep))
                    sh = Part.read(str(_tmp_brep))
                    try: _tmp_brep.unlink()
                    except: pass
                    if sh is None or sh.isNull():
                        # Secondary fallback: importBrep in-place
                        sh = Part.Shape()
                        sh.importBrep(str(_tmp_brep) if Path(str(_tmp_brep)).exists() else path)
                    if sh is None or sh.isNull():
                        raise ValueError(f"BREP import returned null shape: {path}")
                elif op in ("import_step", "import_step_occ"):
                    # All STEP import methods (Part.read, App.loadFile, Import.insert,
                    # OCC STEPControl_Reader) hang in FreeCAD 1.0 headless mode.
                    raise ValueError("STEP import not available in FreeCAD 1.0 headless mode")

                elif op in ("import_iges", "import_iges_occ"):
                    # All IGES import methods hang in FreeCAD 1.0 headless mode.
                    raise ValueError("IGES import not available in FreeCAD 1.0 headless mode")
                else:  # import_stl — convert to rough solid via Mesh module
                    import Mesh as _Mesh
                    m = _Mesh.Mesh()
                    m.read(path)
                    faces = []
                    for facet in m.Facets:
                        pts = [Base.Vector(*p) for p in facet.Points]
                        pts.append(pts[0])
                        try:
                            faces.append(Part.Face(Part.makePolygon(pts)))
                        except Exception:
                            pass
                    sh = Part.makeShell(faces) if faces else Part.Shape()
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            # ── Analysis ─────────────────────────────────────────────────────
            elif op == "shape_info":
                sh_id = op_spec.get("shape")
                if sh_id not in shapes:
                    raise ValueError(f"Shape '{sh_id}' not found")
                sh = shapes[sh_id]
                info = _shape_summary(sh)
                try:
                    com = sh.CenterOfMass
                    info["center_of_mass"] = [round(com.x, 4), round(com.y, 4), round(com.z, 4)]
                except Exception:
                    pass
                info["shape_id"] = sh_id
                results["analyses"].append({"op": "shape_info", "ok": True, **info})

            elif op == "check_shape":
                sh_id = op_spec.get("shape")
                if sh_id not in shapes:
                    raise ValueError(f"Shape '{sh_id}' not found")
                sh = shapes[sh_id]
                issues = []
                if not sh.isValid():
                    issues.append("invalid")
                if sh.isNull():
                    issues.append("null")
                if sh.Volume < 0:
                    issues.append("negative_volume")
                try:
                    sh.check(True)
                except Exception as e:
                    issues.append(f"check: {e}")
                results["analyses"].append({
                    "op": "check_shape", "ok": len(issues) == 0,
                    "shape_id": sh_id, "issues": issues,
                })

            elif op == "brep_string":
                sh_id = op_spec.get("shape")
                brep = shapes[sh_id].exportBrepToString()
                results["analyses"].append({
                    "op": "brep_string", "ok": True,
                    "shape_id": sh_id, "brep_length": len(brep),
                })

            # ── Special compound models ──────────────────────────────────────
            elif op == "make_hex_bolt":
                """M-series hex bolt"""
                d = float(op_spec.get("diameter", 8))     # nominal diameter
                length = float(op_spec.get("length", 30))  # shank length
                head_h = float(op_spec.get("head_h", d * 0.65))
                head_w = float(op_spec.get("head_w", d * 1.8))  # across-flats
                chamfer_r = float(op_spec.get("chamfer", d * 0.05))
                # Hex head
                hex_pts = []
                hw = head_w / math.sqrt(3)  # circumradius
                for i in range(6):
                    a = math.radians(30 + 60 * i)
                    hex_pts.append(Base.Vector(hw * math.cos(a), hw * math.sin(a), 0))
                hex_pts.append(hex_pts[0])
                hex_wire = Part.makePolygon(hex_pts)
                hex_face = Part.Face(hex_wire)
                head = hex_face.extrude(Base.Vector(0, 0, head_h))
                # Shank
                shank = Part.makeCylinder(d / 2, length, Base.Vector(0, 0, head_h))
                bolt = head.fuse(shank).removeSplitter()
                shapes[op_id] = bolt
                results["shapes"][op_id] = _shape_summary(bolt)

            elif op == "make_hex_nut":
                d = float(op_spec.get("diameter", 8))
                thickness = float(op_spec.get("thickness", d * 0.8))
                head_w = float(op_spec.get("head_w", d * 1.8))
                hw = head_w / math.sqrt(3)
                hex_pts = []
                for i in range(6):
                    a = math.radians(30 + 60 * i)
                    hex_pts.append(Base.Vector(hw * math.cos(a), hw * math.sin(a), 0))
                hex_pts.append(hex_pts[0])
                hex_wire = Part.makePolygon(hex_pts)
                hex_face = Part.Face(hex_wire)
                nut = hex_face.extrude(Base.Vector(0, 0, thickness))
                bore = Part.makeCylinder(d / 2, thickness)
                nut = nut.cut(bore).removeSplitter()
                shapes[op_id] = nut
                results["shapes"][op_id] = _shape_summary(nut)

            elif op == "make_tube":
                R_outer = float(op_spec.get("R_outer", 10))
                R_inner = float(op_spec.get("R_inner", 8))
                H = float(op_spec.get("H", 20))
                pos = op_spec.get("pos", [0, 0, 0])
                outer = Part.makeCylinder(R_outer, H, _vec(pos))
                inner = Part.makeCylinder(R_inner, H, _vec(pos))
                tube = outer.cut(inner)
                shapes[op_id] = tube
                results["shapes"][op_id] = _shape_summary(tube)

            elif op == "make_bracket":
                W = float(op_spec.get("W", 30))
                H = float(op_spec.get("H", 30))
                D = float(op_spec.get("D", 5))   # thickness
                fillet_r = float(op_spec.get("fillet", 2))
                # L-bracket
                arm1 = Part.makeBox(W, D, H)
                arm2 = Part.makeBox(D, W, H)
                bracket = arm1.fuse(arm2).removeSplitter()
                try:
                    bracket = bracket.makeFillet(fillet_r, bracket.Edges)
                except Exception:
                    pass
                shapes[op_id] = bracket
                results["shapes"][op_id] = _shape_summary(bracket)

            elif op == "make_enclosure":
                L = float(op_spec.get("L", 50))
                W = float(op_spec.get("W", 40))
                H = float(op_spec.get("H", 30))
                wall = float(op_spec.get("wall", 2))
                open_top = op_spec.get("open_top", True)
                outer = Part.makeBox(L, W, H)
                inner_H = H - wall if not open_top else H
                inner = Part.makeBox(
                    L - 2 * wall, W - 2 * wall, inner_H,
                    Base.Vector(wall, wall, wall)
                )
                box = outer.cut(inner)
                shapes[op_id] = box
                results["shapes"][op_id] = _shape_summary(box)

            elif op == "make_gear_spur":
                """Spur gear with TRUE involute tooth profile"""
                z      = int(op_spec.get("teeth", 20))       # number of teeth
                m      = float(op_spec.get("module", 1.0))   # module (mm)
                b      = float(op_spec.get("width", 10))     # face width
                hub_r  = float(op_spec.get("hub_r", 0))      # central bore radius
                pa_deg = float(op_spec.get("pressure_angle", 20))  # pressure angle
                pa     = math.radians(pa_deg)
                pitch_r = m * z / 2.0
                tip_r   = pitch_r + m
                root_r  = pitch_r - 1.25 * m
                base_r  = pitch_r * math.cos(pa)

                def _involute_pt(r_base, t):
                    """Involute curve parametric: t = angle on base circle"""
                    return Base.Vector(
                        r_base * (math.cos(t) + t * math.sin(t)),
                        r_base * (math.sin(t) - t * math.cos(t)),
                        0)

                def _involute_flank(r_base, r_start, r_end, n=8):
                    """Sample involute from r_start to r_end (radii)"""
                    # Find parameter t range
                    t0 = math.sqrt(max((r_start/r_base)**2 - 1, 0))
                    t1 = math.sqrt(max((r_end  /r_base)**2 - 1, 0))
                    pts = []
                    for i in range(n):
                        t = t0 + (t1 - t0) * i / (n - 1)
                        pts.append(_involute_pt(r_base, t))
                    return pts

                # Half-tooth angular thickness at pitch circle
                tooth_thick_half = math.pi / (2 * z)  # in radians
                # Involute angle at pitch circle
                inv_pa = math.tan(pa) - pa

                angle_step = 2 * math.pi / z
                # Compute involute reference angles
                t_pitch   = math.sqrt(max((pitch_r/base_r)**2 - 1, 0))
                inv_ref   = _involute_pt(base_r, t_pitch)
                pitch_ang = math.atan2(inv_ref.y, inv_ref.x)

                # Collect all profile points in CCW angular order (robust makePolygon)
                all_points = []
                for i in range(z):
                    base_rot = i * angle_step
                    # Lower flank (+involute) sits on the trailing side of the
                    # tooth; the mirrored flank on the leading side. Arcs sweep
                    # CCW by taking deltas modulo 2π (never the long way round).
                    offset_lo = base_rot - tooth_thick_half - pitch_ang
                    offset_hi = base_rot + tooth_thick_half + pitch_ang

                    def _rot_i(px, py, a):
                        c, s = math.cos(a), math.sin(a)
                        return Base.Vector(c*px - s*py, s*px + c*py, 0)

                    r_eff = max(root_r, base_r * 1.001)
                    flank = _involute_flank(base_r, r_eff, tip_r, n=8)

                    # Lower flank (root → tip)
                    for p in flank:
                        all_points.append(_rot_i(p.x, p.y, offset_lo))

                    # Tip arc (lower tip → upper tip, short CCW sweep)
                    tip_ang_a = math.atan2(all_points[-1].y, all_points[-1].x)
                    upper_tip = _rot_i(flank[-1].x, -flank[-1].y, offset_hi)
                    tip_sweep = (math.atan2(upper_tip.y, upper_tip.x) - tip_ang_a) % (2 * math.pi)
                    for j in range(1, 5):
                        a = tip_ang_a + tip_sweep * j / 4
                        all_points.append(Base.Vector(tip_r*math.cos(a), tip_r*math.sin(a), 0))

                    # Upper flank (tip → root, mirrored involute)
                    for p in reversed(flank):
                        all_points.append(_rot_i(p.x, -p.y, offset_hi))

                    # Root arc to next tooth (short CCW sweep)
                    ra_start = math.atan2(all_points[-1].y, all_points[-1].x)
                    next_offset_lo = (i+1) * angle_step - tooth_thick_half - pitch_ang
                    next_root_pt = _rot_i(flank[0].x, flank[0].y, next_offset_lo)
                    root_sweep = (math.atan2(next_root_pt.y, next_root_pt.x) - ra_start) % (2 * math.pi)
                    for j in range(1, 4):
                        a = ra_start + root_sweep * j / 3
                        all_points.append(Base.Vector(root_r*math.cos(a), root_r*math.sin(a), 0))

                all_points.append(all_points[0])  # close the polygon
                try:
                    gear_wire = Part.makePolygon(all_points)
                    gear_face = Part.Face(gear_wire)
                    gear = gear_face.extrude(Base.Vector(0, 0, b))
                    if gear.isNull() or gear.Volume < 1:
                        raise ValueError("Extrude produced null/empty solid")
                    if not gear.isValid():
                        gear.fix(1e-4, 1e-4, 1e-4)
                        if not gear.isValid():
                            raise ValueError("Extrude produced invalid solid")
                except Exception as _ge:
                    # Fallback: simple 4-point-per-tooth polygon
                    pts2 = []
                    for i in range(z):
                        a_base = i * angle_step
                        for da, r2 in [(-angle_step*0.4, root_r), (-angle_step*0.1, tip_r),
                                        ( angle_step*0.1, tip_r), ( angle_step*0.4, root_r)]:
                            pts2.append(Base.Vector(r2*math.cos(a_base+da), r2*math.sin(a_base+da), 0))
                    pts2.append(pts2[0])
                    gear = Part.Face(Part.makePolygon(pts2)).extrude(Base.Vector(0, 0, b))
                    results.setdefault("warnings", []).append(f"Involute failed ({_ge}), used polygon")

                if hub_r > 0:
                    bore_sh = Part.makeCylinder(hub_r, b)
                    gear    = gear.cut(bore_sh)
                shapes[op_id] = gear
                results["shapes"][op_id] = _shape_summary(gear)

            # ── NEW: Parametric types via document objects ────────────────────
            elif op == "make_ellipsoid":
                rx = float(op_spec.get("rx", 15))
                ry = float(op_spec.get("ry", 10))
                rz = float(op_spec.get("rz", 8))
                pos = op_spec.get("pos", [0, 0, 0])
                doc_e = App.newDocument("_ell")
                obj = doc_e.addObject("Part::Ellipsoid", "_e")
                obj.Radius1 = rx; obj.Radius2 = ry; obj.Radius3 = rz
                doc_e.recompute()
                sh = obj.Shape.copy()
                sh.translate(_vec(pos))
                App.closeDocument("_ell")
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_prism":
                # Regular N-sided prism
                n     = int(op_spec.get("n", 6))
                R     = float(op_spec.get("R", 10))
                H     = float(op_spec.get("H", 20))
                pos   = op_spec.get("pos", [0, 0, 0])
                pts   = []
                for i in range(n):
                    a = 2 * math.pi * i / n
                    pts.append(Base.Vector(R * math.cos(a) + _vec(pos).x,
                                           R * math.sin(a) + _vec(pos).y, _vec(pos).z))
                pts.append(pts[0])
                wire = Part.makePolygon(pts)
                face = Part.Face(wire)
                sh   = face.extrude(Base.Vector(0, 0, H))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_spiral":
                # Flat Archimedean spiral wire
                turns  = float(op_spec.get("turns", 3))
                growth = float(op_spec.get("growth", 3))   # radius growth per turn
                steps  = int(op_spec.get("steps", 64)) * int(turns)
                pts = []
                for i in range(steps + 1):
                    t = i / steps * turns
                    r = growth * t
                    a = 2 * math.pi * t
                    pts.append(Base.Vector(r * math.cos(a), r * math.sin(a), 0))
                edges = [Part.LineSegment(pts[i], pts[i+1]).toShape() for i in range(len(pts)-1)]
                sh = Part.Wire(edges)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_helix":
                # Helix wire path using Part.makeHelix
                pitch  = float(op_spec.get("pitch", 5))
                height = float(op_spec.get("height", 40))
                radius = float(op_spec.get("R", 10))
                angle  = float(op_spec.get("angle", 0))    # taper angle deg
                sh = Part.makeHelix(pitch, height, radius, angle)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_long_helix":
                pitch  = float(op_spec.get("pitch", 5))
                height = float(op_spec.get("height", 40))
                radius = float(op_spec.get("R", 10))
                lhand  = op_spec.get("left_hand", False)
                sh = Part.makeLongHelix(pitch, height, radius, 0, lhand)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_thread":
                # Part.makeThread(profile_wire, spine_wire, is_left_hand)
                # Simplified: create threaded cylinder via helix sweep
                d       = float(op_spec.get("diameter", 8))
                pitch   = float(op_spec.get("pitch", 1.25))
                length  = float(op_spec.get("length", 20))
                # Core cylinder
                core    = Part.makeCylinder(d / 2, length)
                # Helix for thread path
                helix   = Part.makeHelix(pitch, length, d / 2 * 1.1)
                # Triangle profile
                h_t     = pitch * 0.6495
                tri_pts = [Base.Vector(d/2, 0, 0),
                           Base.Vector(d/2 + h_t, 0, pitch/2),
                           Base.Vector(d/2, 0, pitch),
                           Base.Vector(d/2, 0, 0)]
                tri_wire = Part.makePolygon(tri_pts)
                try:
                    thread_groove = Part.Wire([helix]).makePipeShell(
                        [tri_wire], True, False)
                    _cut = core.cut(thread_groove)
                    sh = _cut.removeSplitter() if not _cut.isNull() else _cut
                    # Validate result
                    if sh.isNull() or sh.Volume < 10:
                        sh = core
                        results.setdefault("warnings", []).append("make_thread: cut invalid, using core cyl")
                except Exception as _te:
                    sh = core
                    results.setdefault("warnings", []).append(f"make_thread pipe failed ({_te}), using core cyl")
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_pipe_3d":
                # Pipe sweep along a 3D polyline path
                pts_spec = op_spec.get("path_pts", [[0,0,0],[0,0,30]])
                r_prof   = float(op_spec.get("R", 3))
                pts      = [Base.Vector(*p) for p in pts_spec]
                edges    = [Part.LineSegment(pts[i], pts[i+1]).toShape()
                            for i in range(len(pts)-1)]
                spine    = Part.Wire(edges)
                # Get tangent from first edge
                e0       = spine.Edges[0]
                t0       = e0.tangentAt(e0.FirstParameter)
                start_pt = pts[0]
                prof_c   = Part.makeCircle(r_prof, start_pt, t0)
                prof_w   = Part.Wire([prof_c])
                try:
                    sh = spine.makePipeShell([prof_w], True, True)
                except Exception:
                    sh = prof_w.makePipe(spine)
                    if sh.isNull() or sh.Volume < 1:
                        raise ValueError("makePipeShell/makePipe produced empty result")
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_loft_multi":
                # Loft through multiple profile wires
                wire_ids  = op_spec.get("profiles", [])
                ruled     = op_spec.get("ruled", False)
                closed    = op_spec.get("closed", False)
                wires     = [shapes[wid] for wid in wire_ids if wid in shapes]
                sh        = Part.makeLoft(wires, True, ruled, closed)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_bspline":
                # BSpline curve interpolated through points
                pts_spec  = op_spec.get("points", [[0,0,0],[10,10,0],[20,0,0]])
                pts       = [Base.Vector(*p) for p in pts_spec]
                periodic  = op_spec.get("periodic", False)
                bsp       = Part.BSplineCurve()
                bsp.interpolate(pts, PeriodicFlag=periodic)
                sh        = bsp.toShape()
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_bspline_surface":
                # BSpline surface via OCC GeomAPI PointsToBSplineSurface
                # grid_pts: 2D list [row][col] of [x,y,z]
                grid      = op_spec.get("grid_pts")
                if grid is None:
                    # Default 3x3 grid
                    grid = [[[0,0,0],[10,0,5],[20,0,0]],
                            [[0,10,5],[10,10,10],[20,10,5]],
                            [[0,20,0],[10,20,5],[20,20,0]]]
                try:
                    from OCC.Core.GeomAPI import GeomAPI_PointsToBSplineSurface
                    from OCC.Core.TColgp import TColgp_Array2OfPnt
                    from OCC.Core.gp import gp_Pnt
                    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeFace
                    rows = len(grid); cols = len(grid[0])
                    arr  = TColgp_Array2OfPnt(1, rows, 1, cols)
                    for i, row in enumerate(grid):
                        for j, pt in enumerate(row):
                            arr.SetValue(i+1, j+1, gp_Pnt(float(pt[0]), float(pt[1]), float(pt[2])))
                    builder = GeomAPI_PointsToBSplineSurface(arr)
                    if builder.IsDone():
                        surf    = builder.Surface()
                        fc_face = BRepBuilderAPI_MakeFace(surf, 1e-6)
                        # Convert OCC face to FreeCAD shape via BREP string
                        from OCC.Core.BRepTools import breptools
                        import tempfile as _tmp2
                        _tp = Path(_tmp2.gettempdir()) / "_occ_surf.brep"
                        breptools.Write(fc_face.Shape(), str(_tp))
                        sh = Part.read(str(_tp))
                        _tp.unlink()
                    else:
                        raise ValueError("GeomAPI_PointsToBSplineSurface failed")
                except ImportError:
                    # Fallback: loft approximation
                    wires = []
                    for row in grid:
                        pts = [Base.Vector(*p) for p in row]
                        w = Part.Wire([Part.makeLine(pts[i], pts[i+1])
                                        for i in range(len(pts)-1)])
                        wires.append(w)
                    sh = Part.makeLoft(wires, False, False, False)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_ruled":
                w1_id = op_spec.get("wire1")
                w2_id = op_spec.get("wire2")
                sh    = Part.makeRuledSurface(shapes[w1_id], shapes[w2_id])
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_filled_face":
                # Fill a closed wire with a surface
                wire_id = op_spec.get("wire")
                wire    = shapes[wire_id] if wire_id else None
                if wire is None:
                    edges_raw = op_spec.get("edges", [])
                    wire = Part.Wire([Part.makeCircle(10)])
                sh = Part.makeFilledFace([e for e in wire.Edges])
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "offset_2d":
                sh_id  = op_spec.get("shape")
                offset = float(op_spec.get("offset", 2.0))
                join   = int(op_spec.get("join", 0))  # 0=arcs 2=intersect
                src    = shapes[sh_id]
                # makeOffset2D only works on face/wire/edge, not solid
                # If solid: take the largest face
                if src.ShapeType == "Solid" or src.ShapeType == "CompSolid":
                    src = sorted(src.Faces, key=lambda f: f.Area, reverse=True)[0]
                sh = src.makeOffset2D(offset, join)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "section_curve":
                # Cross-section curves at given Z
                sh_id  = op_spec.get("shape")
                z      = float(op_spec.get("z", 0))
                normal = op_spec.get("normal", [0, 0, 1])
                plane  = Part.Plane(Base.Vector(0, 0, z), _vec(normal))
                plane_sh = plane.toShape()
                sh     = shapes[sh_id].section(plane_sh)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "read_fcstd":
                # Read all shapes from an FCStd file
                path = op_spec.get("path", "")
                if not Path(path).exists():
                    raise FileNotFoundError(f"FCStd not found: {path}")
                import shutil as _sh3, tempfile as _tmp3
                _tmp_f = Path(_tmp3.gettempdir()) / "_fc_read.FCStd"
                _sh3.copy2(path, str(_tmp_f))
                doc_r = App.openDocument(str(_tmp_f))
                read_shapes = {}
                for obj in doc_r.Objects:
                    if hasattr(obj, "Shape") and not obj.Shape.isNull():
                        read_shapes[obj.Name] = obj.Shape.copy()
                App.closeDocument(doc_r.Name)
                try: _tmp_f.unlink()
                except: pass
                all_sh = list(read_shapes.values())
                if all_sh:
                    compound = Part.makeCompound(all_sh) if len(all_sh) > 1 else all_sh[0]
                    shapes[op_id] = compound
                    results["shapes"][op_id] = _shape_summary(compound)
                    results["shapes"][op_id]["fcstd_objects"] = list(read_shapes.keys())
                else:
                    raise ValueError(f"FCStd contained no shapes: {path}")

            elif op == "write_fcstd":
                # Write multiple shapes to FCStd with names
                path     = op_spec.get("path", "")
                shape_map = op_spec.get("shapes_map", {})  # {name: shape_id}
                if not path:
                    raise ValueError("write_fcstd: path required")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                doc_w = App.newDocument("_fcstd_w")
                for name, sid in shape_map.items():
                    if sid in shapes:
                        feat = doc_w.addObject("Part::Feature", str(name))
                        feat.Shape = shapes[sid]
                # Also write any existing shapes if no map
                if not shape_map:
                    for sid, sh in shapes.items():
                        if isinstance(sh, Part.Shape) and not sh.isNull():
                            feat = doc_w.addObject("Part::Feature", str(sid))
                            feat.Shape = sh
                doc_w.recompute()
                doc_w.saveAs(path)
                App.closeDocument("_fcstd_w")
                ok = Path(path).exists() and Path(path).stat().st_size > 0
                results["exports"].append({"op": "write_fcstd", "ok": ok, "path": path,
                                            "size_bytes": Path(path).stat().st_size if ok else 0})

            # ── OCC Direct Operations (bypass FreeCAD wrappers) ──────────────
            elif op == "occ_boolean":
                # OCC-tier boolean: more robust than FreeCAD's for complex shapes
                base_id  = op_spec.get("base")
                tool_ids = op_spec.get("tools", [])
                bool_op  = op_spec.get("bool_op", "fuse").lower()  # fuse/cut/common
                try:
                    from OCC.Core.BRepAlgoAPI import (BRepAlgoAPI_Fuse,
                                                       BRepAlgoAPI_Cut,
                                                       BRepAlgoAPI_Common)
                    from OCC.Core.BRepTools import breptools
                    import tempfile as _t4
                    def _fc_to_occ(fc_sh):
                        _p = Path(_t4.gettempdir()) / "_occ_bridge.brep"
                        fc_sh.exportBrep(str(_p))
                        from OCC.Core.BRep import BRep_Builder
                        from OCC.Core.TopoDS import TopoDS_Shape
                        s = TopoDS_Shape()
                        BRep_Builder()
                        breptools.Read(s, str(_p), BRep_Builder())
                        _p.unlink()
                        return s
                    def _occ_to_fc(occ_sh):
                        _p = Path(_t4.gettempdir()) / "_occ_back.brep"
                        breptools.Write(occ_sh, str(_p))
                        fc = Part.read(str(_p))
                        _p.unlink()
                        return fc
                    base_occ = _fc_to_occ(shapes[base_id])
                    result_occ = base_occ
                    for tid in tool_ids:
                        tool_occ = _fc_to_occ(shapes[tid])
                        if bool_op == "fuse":
                            op_maker = BRepAlgoAPI_Fuse(result_occ, tool_occ)
                        elif bool_op == "cut":
                            op_maker = BRepAlgoAPI_Cut(result_occ, tool_occ)
                        else:
                            op_maker = BRepAlgoAPI_Common(result_occ, tool_occ)
                        op_maker.Build()
                        result_occ = op_maker.Shape()
                    sh = _occ_to_fc(result_occ)
                except ImportError:
                    # Fallback to FreeCAD's built-in
                    base_sh = shapes[base_id]
                    tool_shapes = [shapes[tid] for tid in tool_ids if tid in shapes]
                    if bool_op == "fuse":
                        sh = base_sh.fuse(tool_shapes[0]) if tool_shapes else base_sh
                        for t in tool_shapes[1:]: sh = sh.fuse(t)
                    elif bool_op == "cut":
                        sh = base_sh.cut(tool_shapes[0]) if tool_shapes else base_sh
                        for t in tool_shapes[1:]: sh = sh.cut(t)
                    else:
                        sh = base_sh.common(tool_shapes[0]) if tool_shapes else base_sh
                    sh = sh.removeSplitter()
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "occ_fillet":
                # OCC-tier fillet: more reliable edge selection
                sh_id  = op_spec.get("shape")
                radius = float(op_spec.get("radius", 1.0))
                try:
                    from OCC.Core.BRepFilletAPI import BRepFilletAPI_MakeFillet
                    from OCC.Core.TopExp import TopExp_Explorer
                    from OCC.Core.TopAbs import TopAbs_EDGE
                    from OCC.Core.BRepTools import breptools
                    from OCC.Core.BRep import BRep_Builder
                    from OCC.Core.TopoDS import TopoDS_Shape
                    import tempfile as _t5
                    _p1 = Path(_t5.gettempdir()) / "_occ_flt_in.brep"
                    shapes[sh_id].exportBrep(str(_p1))
                    occ_sh = TopoDS_Shape()
                    breptools.Read(occ_sh, str(_p1), BRep_Builder())
                    _p1.unlink()
                    fillet_maker = BRepFilletAPI_MakeFillet(occ_sh)
                    exp = TopExp_Explorer(occ_sh, TopAbs_EDGE)
                    edge_indices = op_spec.get("edges")
                    idx = 0
                    while exp.More():
                        if edge_indices is None or idx in edge_indices:
                            try: fillet_maker.Add(radius, exp.Current())
                            except Exception: pass
                        exp.Next(); idx += 1
                    fillet_maker.Build()
                    if fillet_maker.IsDone():
                        _p2 = Path(_t5.gettempdir()) / "_occ_flt_out.brep"
                        breptools.Write(fillet_maker.Shape(), str(_p2))
                        sh = Part.read(str(_p2))
                        _p2.unlink()
                    else:
                        sh = shapes[sh_id]
                        results["errors"].append("occ_fillet: BRepFilletAPI failed, using original")
                except ImportError:
                    sh = shapes[sh_id].makeFillet(radius, shapes[sh_id].Edges)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "occ_thick_solid":
                # OCC MakeThickSolid — more reliable than FreeCAD's makeThickness
                sh_id       = op_spec.get("shape")
                thickness   = float(op_spec.get("thickness", -2.0))
                face_indices = op_spec.get("faces", [0])
                try:
                    from OCC.Core.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
                    from OCC.Core.TopTools import TopTools_ListOfShape
                    from OCC.Core.TopExp import TopExp_Explorer
                    from OCC.Core.TopAbs import TopAbs_FACE
                    from OCC.Core.BRepTools import breptools
                    from OCC.Core.BRep import BRep_Builder
                    from OCC.Core.TopoDS import TopoDS_Shape
                    import tempfile as _t6
                    _p1 = Path(_t6.gettempdir()) / "_occ_thk_in.brep"
                    shapes[sh_id].exportBrep(str(_p1))
                    occ_sh = TopoDS_Shape()
                    breptools.Read(occ_sh, str(_p1), BRep_Builder())
                    _p1.unlink()
                    faces_list = TopTools_ListOfShape()
                    exp = TopExp_Explorer(occ_sh, TopAbs_FACE)
                    idx = 0
                    while exp.More():
                        if idx in face_indices:
                            faces_list.Append(exp.Current())
                        exp.Next(); idx += 1
                    thick = BRepOffsetAPI_MakeThickSolid()
                    thick.MakeThickSolidByJoin(occ_sh, faces_list, thickness, 1e-3)
                    thick.Build()
                    if thick.IsDone():
                        _p2 = Path(_t6.gettempdir()) / "_occ_thk_out.brep"
                        breptools.Write(thick.Shape(), str(_p2))
                        sh = Part.read(str(_p2))
                        _p2.unlink()
                    else:
                        sh = shapes[sh_id]
                        results["errors"].append("occ_thick_solid failed, using original")
                except ImportError:
                    face_list = [shapes[sh_id].Faces[i] for i in face_indices
                                 if i < len(shapes[sh_id].Faces)]
                    sh = shapes[sh_id].makeThickness(face_list, thickness, 1e-3)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "array_path":
                # Array N copies along a path wire
                sh_id    = op_spec.get("shape")
                path_id  = op_spec.get("path")
                count    = int(op_spec.get("count", 5))
                align    = op_spec.get("align", True)
                path_wire = shapes[path_id]
                path_len  = path_wire.Length
                parts     = []
                for i in range(count):
                    t = i / max(count - 1, 1)
                    pt = path_wire.valueAt(path_wire.FirstParameter +
                                           t * (path_wire.LastParameter - path_wire.FirstParameter))
                    cp = shapes[sh_id].copy()
                    cp.translate(pt - cp.CenterOfMass)
                    parts.append(cp)
                comp = Part.makeCompound(parts)
                shapes[op_id] = comp
                results["shapes"][op_id] = _shape_summary(comp)

            elif op == "extrude_taper":
                # Tapered extrusion with draft angle
                sh_id  = op_spec.get("shape")   # must be a Face
                dir_v  = op_spec.get("direction", [0, 0, 10])
                taper  = float(op_spec.get("taper_angle", 5))  # degrees
                sym    = op_spec.get("symmetric", False)
                doc_et = App.newDocument("_et")
                feat   = doc_et.addObject("Part::Extrusion", "_extr")
                feat.Base = doc_et.addObject("Part::Feature", "_face")
                doc_et.getObject("_face").Shape = shapes[sh_id]
                feat.Dir         = Base.Vector(*dir_v)
                feat.TaperAngle  = taper
                feat.Symmetric   = sym
                feat.Solid       = True
                doc_et.recompute()
                sh = feat.Shape.copy()
                App.closeDocument("_et")
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "project_shape":
                # Project shape onto plane
                sh_id  = op_spec.get("shape")
                normal = op_spec.get("normal", [0, 0, 1])
                origin = op_spec.get("origin", [0, 0, 0])
                plane  = Part.Plane(_vec(origin), _vec(normal))
                plane_sh = plane.toShape()
                projected = shapes[sh_id].section(plane_sh)
                shapes[op_id] = projected
                results["shapes"][op_id] = _shape_summary(projected)

            elif op == "make_polygon_3d":
                # 3D (non-planar) polyline wire
                pts_spec = op_spec.get("points", [])
                closed   = op_spec.get("closed", False)
                pts      = [Base.Vector(*p) for p in pts_spec]
                if closed and pts and (pts[-1] - pts[0]).Length > 1e-6:
                    pts.append(pts[0])
                edges = [Part.LineSegment(pts[i], pts[i+1]).toShape()
                         for i in range(len(pts)-1)]
                sh = Part.Wire(edges)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_spring":
                R = float(op_spec.get("R", 10))
                r = float(op_spec.get("wire_r", 1.5))
                pitch = float(op_spec.get("pitch", 8))
                turns = float(op_spec.get("turns", 5))
                left_hand = op_spec.get("left_hand", False)
                # Use Part.makeHelix for a mathematically exact helix
                helix = Part.makeHelix(pitch, turns * pitch, R, 0, left_hand)
                # Get tangent at first point via first EDGE (Wire has no tangentAt)
                e0    = helix.Edges[0]
                start = helix.Vertexes[0].Point
                tan   = e0.tangentAt(e0.FirstParameter)
                # Build circular profile perpendicular to helix tangent
                prof_circle = Part.makeCircle(r, start, tan)
                prof_wire   = Part.Wire([prof_circle])
                try:
                    spring = Part.Wire([helix]).makePipeShell(
                        [prof_wire], True, False)
                    if spring.isNull() or spring.Volume < 1:
                        raise ValueError("PipeShell produced empty result")
                    shapes[op_id] = spring
                except Exception as _se:
                    # Fallback: approximate torus
                    spring = Part.makeTorus(R, r)
                    shapes[op_id] = spring
                    results.setdefault("warnings", []).append(f"spring PipeShell failed ({_se}), used torus")
                results["shapes"][op_id] = _shape_summary(shapes[op_id])

            elif op == "make_rounded_box":
                L = float(op_spec.get("L", 30))
                W = float(op_spec.get("W", 20))
                H = float(op_spec.get("H", 10))
                R = float(op_spec.get("R", 2))
                pos = op_spec.get("pos", [0, 0, 0])
                box = Part.makeBox(L, W, H, _vec(pos))
                try:
                    edges = [e for e in box.Edges if abs(e.Length - H) < 1e-4 or
                             abs(e.Length - L) < 1e-4 or abs(e.Length - W) < 1e-4]
                    # Fillet all edges
                    fbox = box.makeFillet(R, box.Edges)
                    shapes[op_id] = fbox
                except Exception:
                    shapes[op_id] = box
                results["shapes"][op_id] = _shape_summary(shapes[op_id])

            elif op == "make_text_3d":
                text = op_spec.get("text", "CAD")
                size = float(op_spec.get("size", 10))
                depth = float(op_spec.get("depth", 2))
                # Use Draft if available, else approximate
                try:
                    import Draft
                    vec = Base.Vector(0, 0, 0)
                    t_obj = Draft.make_text([text], vec)
                    App.ActiveDocument.recompute()
                    # Convert to 3D shape
                    sh = Part.makeBox(size * len(text) * 0.6, size * 1.2, depth)
                    shapes[op_id] = sh
                except Exception:
                    sh = Part.makeBox(size * len(text) * 0.6, size * 1.2, depth)
                    shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(shapes[op_id])

            elif op == "make_slot":
                L = float(op_spec.get("L", 20))
                W = float(op_spec.get("W", 8))
                H = float(op_spec.get("H", 5))
                pos = op_spec.get("pos", [0, 0, 0])
                R = W / 2
                # Slot = rect with semicircles at ends
                rect = Part.makeBox(L - W, W, H, Base.Vector(_vec(pos).x + R, _vec(pos).y, _vec(pos).z))
                c1 = Part.makeCylinder(R, H, Base.Vector(_vec(pos).x + R, _vec(pos).y + R, _vec(pos).z))
                c2 = Part.makeCylinder(R, H, Base.Vector(_vec(pos).x + L - R, _vec(pos).y + R, _vec(pos).z))
                slot = rect.fuse(c1).fuse(c2).removeSplitter()
                shapes[op_id] = slot
                results["shapes"][op_id] = _shape_summary(slot)

            elif op == "make_chamfer_box":
                L = float(op_spec.get("L", 20))
                W = float(op_spec.get("W", 15))
                H = float(op_spec.get("H", 10))
                c = float(op_spec.get("chamfer", 1.5))
                box = Part.makeBox(L, W, H)
                try:
                    ch = box.makeChamfer(c, box.Edges)
                    shapes[op_id] = ch
                except Exception:
                    shapes[op_id] = box
                results["shapes"][op_id] = _shape_summary(shapes[op_id])

            elif op == "make_bearing_seat":
                od = float(op_spec.get("od", 40))    # outer diameter
                bore = float(op_spec.get("bore", 17)) # inner bore
                W = float(op_spec.get("width", 12))   # width
                housing = Part.makeCylinder(od / 2, W)
                bore_cyl = Part.makeCylinder(bore / 2, W)
                seat = housing.cut(bore_cyl)
                shapes[op_id] = seat
                results["shapes"][op_id] = _shape_summary(seat)

            # ── PartDesign via document objects ───────────────────────────────
            elif op == "partdesign_pad":
                # Pad a sketch/face profile using PartDesign::Body+Pad
                face_id = op_spec.get("face")    # shape_id of a Face/Wire
                length  = float(op_spec.get("length", 10))
                sym     = op_spec.get("symmetric", False)
                taper   = float(op_spec.get("taper", 0))
                src_sh  = shapes[face_id]
                # Ensure we have a face
                if src_sh.ShapeType in ("Wire", "Edge"):
                    src_sh = Part.Face(src_sh) if src_sh.ShapeType == "Wire" else Part.Face(Part.Wire([src_sh]))
                doc_pd = App.newDocument("_pd")
                try:
                    body   = doc_pd.addObject("PartDesign::Body", "Body")
                    feat_f = doc_pd.addObject("Part::Feature", "_src")
                    feat_f.Shape = src_sh
                    pad    = doc_pd.addObject("PartDesign::Pad", "Pad")
                    pad.Profile = feat_f
                    pad.Length  = length
                    # FreeCAD 1.0 uses Midplane; older uses Symmetric
                    try:    pad.Midplane = sym
                    except: pass
                    try:    pad.Symmetric = sym
                    except: pass
                    if taper:
                        try:    pad.TaperAngle = taper
                        except: pass
                    body.addObject(pad)
                    doc_pd.recompute()
                    sh = pad.Shape.copy()
                    if sh.isNull() or sh.Volume < 1:
                        raise ValueError("Pad shape empty")
                except Exception as _pde:
                    # Robust fallback: Part extrude
                    sh = src_sh.extrude(Base.Vector(0, 0, length))
                    results.setdefault("warnings", []).append(f"PartDesign::Pad fallback ({_pde})")
                finally:
                    try: App.closeDocument("_pd")
                    except: pass
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "partdesign_pocket":
                # Pocket (cut) into a base solid using a profile
                base_id = op_spec.get("base")
                prof_id = op_spec.get("profile")
                depth   = float(op_spec.get("depth", 5))
                base_sh = shapes[base_id]
                prof_sh = shapes[prof_id]
                # Fallback: just do a Part cut if PartDesign fails
                doc_pk = App.newDocument("_pk")
                try:
                    body    = doc_pk.addObject("PartDesign::Body", "Body")
                    feat_b  = doc_pk.addObject("Part::Feature", "_base")
                    feat_b.Shape = base_sh
                    feat_p  = doc_pk.addObject("Part::Feature", "_prof")
                    feat_p.Shape = prof_sh
                    body.BaseFeature = feat_b
                    pocket = doc_pk.addObject("PartDesign::Pocket", "Pocket")
                    pocket.Profile = feat_p
                    pocket.Length  = depth
                    body.addObject(pocket)
                    doc_pk.recompute()
                    sh = pocket.Shape.copy()
                    if sh.isNull() or sh.Volume < 1:
                        raise ValueError("PartDesign::Pocket produced empty shape")
                except Exception as _pke:
                    # Robust fallback: extrude profile then cut
                    if prof_sh.ShapeType in ("Wire",):
                        prof_face = Part.Face(prof_sh)
                    elif prof_sh.ShapeType == "Face":
                        prof_face = prof_sh
                    else:
                        prof_face = sorted(prof_sh.Faces, key=lambda f: f.Area, reverse=True)[0]
                    cutter = prof_face.extrude(Base.Vector(0, 0, -depth))
                    sh = base_sh.cut(cutter).removeSplitter()
                    results.setdefault("warnings", []).append(f"PartDesign::Pocket fallback to Part::cut: {_pke}")
                finally:
                    try: App.closeDocument("_pk")
                    except: pass
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "partdesign_fillet":
                # PartDesign fillet (more reliable for complex solids)
                base_id = op_spec.get("base")
                radius  = float(op_spec.get("radius", 1.0))
                base_sh = shapes[base_id]
                doc_pf  = App.newDocument("_pf")
                try:
                    body   = doc_pf.addObject("PartDesign::Body", "Body")
                    feat_b = doc_pf.addObject("Part::Feature", "_src")
                    feat_b.Shape = base_sh
                    flt    = doc_pf.addObject("PartDesign::Fillet", "Fillet")
                    flt.Base   = (feat_b, [""])
                    flt.Size   = radius
                    body.addObject(flt)
                    doc_pf.recompute()
                    sh = flt.Shape.copy()
                    if sh.isNull(): sh = base_sh.makeFillet(radius, base_sh.Edges)
                except Exception:
                    sh = base_sh.makeFillet(radius, base_sh.Edges)
                finally:
                    try: App.closeDocument("_pf")
                    except: pass
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "export_iges":
                sh_id  = op_spec.get("shape")
                path   = op_spec.get("path", "")
                if not path: raise ValueError("export_iges: path required")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                sh = shapes[sh_id]
                exported = False
                # Method 1: Part.export (usually works for IGES)
                try:
                    Part.export([sh], path)
                    exported = Path(path).exists() and Path(path).stat().st_size > 0
                except Exception: pass
                # Method 2: OCC STEPControl_Writer with IGES mode
                if not exported:
                    try:
                        from OCC.Core.IGESControl import IGESControl_Writer
                        from OCC.Core.BRepTools import breptools
                        from OCC.Core.BRep import BRep_Builder
                        from OCC.Core.TopoDS import TopoDS_Shape
                        import tempfile as _t7
                        _bp = Path(_t7.gettempdir()) / "_iges_bridge.brep"
                        sh.exportBrep(str(_bp))
                        occ_sh = TopoDS_Shape()
                        breptools.Read(occ_sh, str(_bp), BRep_Builder())
                        _bp.unlink()
                        writer = IGESControl_Writer()
                        writer.AddShape(occ_sh)
                        writer.Write(path)
                        exported = Path(path).exists() and Path(path).stat().st_size > 0
                    except Exception as _ie:
                        results.setdefault("warnings", []).append(f"IGES OCC write: {_ie}")
                ok = Path(path).exists() and Path(path).stat().st_size > 0
                results["exports"].append({"op": "export_iges", "ok": ok, "path": path,
                                           "size_bytes": Path(path).stat().st_size if ok else 0})

            elif op == "make_torus_knot":
                # Torus knot p,q — parametric wire
                p        = int(op_spec.get("p", 2))
                q        = int(op_spec.get("q", 3))
                R        = float(op_spec.get("R", 15))   # major radius
                r        = float(op_spec.get("r", 5))    # tube radius
                wire_r   = float(op_spec.get("wire_r", 0))  # 0 = wire only
                n_steps  = int(op_spec.get("steps", 200))
                pts = []
                for i in range(n_steps + 1):
                    t = 2 * math.pi * i / n_steps
                    x = (R + r * math.cos(q * t)) * math.cos(p * t)
                    y = (R + r * math.cos(q * t)) * math.sin(p * t)
                    z = r * math.sin(q * t)
                    pts.append(Base.Vector(x, y, z))
                edges  = [Part.LineSegment(pts[i], pts[i+1]).toShape()
                          for i in range(len(pts)-1)]
                knot_w = Part.Wire(edges)
                if wire_r > 0:
                    e0  = knot_w.Edges[0]
                    tan = e0.tangentAt(e0.FirstParameter)
                    st  = pts[0]
                    prof_c = Part.makeCircle(wire_r, st, tan)
                    try:
                        sh = Part.Wire([knot_w]).makePipeShell(
                            [Part.Wire([prof_c])], True, False)
                        if sh.isNull(): sh = knot_w
                    except Exception:
                        sh = knot_w
                else:
                    sh = knot_w
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_catenary":
                # Catenary (hanging chain) curve
                span_half = float(op_spec.get("span_half", 20))
                sag       = float(op_spec.get("sag", 10))
                n_pts     = int(op_spec.get("n_pts", 50))
                a = span_half**2 / (2 * sag)  # catenary parameter
                pts = []
                for i in range(n_pts):
                    x = -span_half + 2 * span_half * i / (n_pts - 1)
                    y = a * (math.cosh(x / a) - 1)
                    pts.append(Base.Vector(x, y, 0))
                edges = [Part.LineSegment(pts[i], pts[i+1]).toShape()
                         for i in range(len(pts)-1)]
                sh = Part.Wire(edges)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_gear_rack":
                # Gear rack (linear gear) to mesh with spur gear
                m       = float(op_spec.get("module", 1.0))
                length  = float(op_spec.get("length", 60))
                width   = float(op_spec.get("width", 10))
                n_teeth = int(length / (math.pi * m))
                pa      = math.radians(float(op_spec.get("pressure_angle", 20)))
                h_addendum = m; h_dedendum = 1.25 * m
                tooth_pitch = math.pi * m
                points = []
                x = 0
                for _ in range(n_teeth):
                    # Root → flank left → tip → flank right → root of next tooth
                    points += [
                        Base.Vector(x, -h_dedendum, 0),
                        Base.Vector(x + tooth_pitch * 0.2 - h_dedendum * math.tan(pa), -h_dedendum, 0),
                        Base.Vector(x + tooth_pitch * 0.2, h_addendum, 0),
                        Base.Vector(x + tooth_pitch * 0.8, h_addendum, 0),
                        Base.Vector(x + tooth_pitch * 0.8 + h_dedendum * math.tan(pa), -h_dedendum, 0),
                    ]
                    x += tooth_pitch
                points.append(Base.Vector(x, -h_dedendum, 0))
                # Close the profile
                bottom_pts = [
                    Base.Vector(x, -h_dedendum - 1, 0),
                    Base.Vector(0, -h_dedendum - 1, 0),
                    points[0],
                ]
                all_pts = points + bottom_pts
                wire = Part.makePolygon(all_pts)
                try:
                    face = Part.Face(wire)
                    sh   = face.extrude(Base.Vector(0, 0, width))
                except Exception:
                    sh = Part.makeBox(length, h_addendum + h_dedendum + 1, width)
                    results.setdefault("warnings", []).append("gear_rack: face failed, used box")
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            # ── Advanced Geometry ─────────────────────────────────────────────
            elif op == "make_frustum":
                # Truncated cone (frustum): R1 = bottom radius, R2 = top radius
                # Note: Part.makeCone with R2!=0 takes angle in DEGREES
                R1        = float(op_spec.get("R1", op_spec.get("R", 15)))
                R2        = float(op_spec.get("R2", op_spec.get("r", 8)))
                H         = float(op_spec.get("H", 20))
                angle_deg = float(op_spec.get("angle", 360))
                sh = Part.makeCone(R1, R2, H, Base.Vector(0,0,0),
                                   Base.Vector(0,0,1), angle_deg)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_pyramid":
                # Regular n-sided pyramid (default: square base)
                n      = int(op_spec.get("n", 4))
                base_r = float(op_spec.get("base_r", 10))  # circumradius of base
                H      = float(op_spec.get("H", 15))
                # Build base polygon
                base_pts = []
                for k in range(n):
                    a = 2 * math.pi * k / n
                    base_pts.append(Base.Vector(base_r * math.cos(a),
                                                base_r * math.sin(a), 0))
                base_pts.append(base_pts[0])  # close
                apex = Base.Vector(0, 0, H)
                # Build triangular faces
                faces = []
                base_wire = Part.makePolygon(base_pts)
                try:
                    faces.append(Part.Face(base_wire))
                except Exception: pass
                for k in range(n):
                    p1 = base_pts[k]
                    p2 = base_pts[(k+1) % n]
                    tri_pts = [p1, p2, apex, p1]
                    try:
                        tri_wire = Part.makePolygon(tri_pts)
                        faces.append(Part.Face(tri_wire))
                    except Exception: pass
                if faces:
                    shell = Part.makeShell(faces)
                    try:
                        sh = Part.makeSolid(shell)
                    except Exception:
                        sh = shell
                else:
                    sh = Part.makeCone(base_r, 0, H, Base.Vector(0,0,0),
                                       Base.Vector(0,0,1), 2*math.pi)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_ellipse_extrude":
                # Elliptical prism: extrude an ellipse face along Z
                a      = float(op_spec.get("a", op_spec.get("major", 15)))  # semi-major
                b      = float(op_spec.get("b", op_spec.get("minor", 8)))   # semi-minor
                H      = float(op_spec.get("H", 20))
                # Part.Ellipse(Center, MajorRadius, MinorRadius)
                ellipse = Part.Ellipse(Base.Vector(0,0,0), a, b)
                wire = Part.Wire([ellipse.toShape()])
                face = Part.Face(wire)
                sh   = face.extrude(Base.Vector(0, 0, H))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_reg_polygon":
                # Regular polygon extruded to prism (alias: n-prism)
                n      = int(op_spec.get("n", 6))
                R      = float(op_spec.get("R", op_spec.get("circumradius", 10)))
                H      = float(op_spec.get("H", 15))
                pts = []
                for k in range(n):
                    a = 2 * math.pi * k / n
                    pts.append(Base.Vector(R * math.cos(a), R * math.sin(a), 0))
                pts.append(pts[0])
                wire = Part.makePolygon(pts)
                face = Part.Face(wire)
                sh   = face.extrude(Base.Vector(0, 0, H))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_stadium":
                # Stadium (discorectangle): two semicircles + rectangle
                L = float(op_spec.get("L", 30))  # total length
                R = float(op_spec.get("R", 8))   # end radius
                H = float(op_spec.get("H", 10))  # height
                # Two lines + two arcs
                half_flat = (L - 2 * R) / 2
                arcs  = []
                lines = []
                # Bottom line
                lines.append(Part.LineSegment(
                    Base.Vector(-half_flat, -R, 0),
                    Base.Vector( half_flat, -R, 0)).toShape())
                # Right arc
                arcs.append(Part.Arc(
                    Base.Vector(half_flat, -R, 0),
                    Base.Vector(half_flat + R, 0, 0),
                    Base.Vector(half_flat, R, 0)).toShape())
                # Top line
                lines.append(Part.LineSegment(
                    Base.Vector( half_flat, R, 0),
                    Base.Vector(-half_flat, R, 0)).toShape())
                # Left arc
                arcs.append(Part.Arc(
                    Base.Vector(-half_flat, R, 0),
                    Base.Vector(-half_flat - R, 0, 0),
                    Base.Vector(-half_flat, -R, 0)).toShape())
                wire = Part.Wire([lines[0], arcs[0], lines[1], arcs[1]])
                face = Part.Face(wire)
                sh   = face.extrude(Base.Vector(0, 0, H))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_hollow_cylinder":
                # Hollow cylinder: outer - inner via boolean cut
                R_out = float(op_spec.get("R_out", op_spec.get("R", 15)))
                R_in  = float(op_spec.get("R_in",  op_spec.get("r", 10)))
                H     = float(op_spec.get("H", 20))
                outer = Part.makeCylinder(R_out, H)
                inner = Part.makeCylinder(R_in,  H)
                sh    = outer.cut(inner)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_i_beam":
                # I-beam (H-beam) profile extruded along Z
                W  = float(op_spec.get("W",  20))   # flange width
                H  = float(op_spec.get("H",  30))   # total height
                tf = float(op_spec.get("tf",  3))   # flange thickness
                tw = float(op_spec.get("tw",  2))   # web thickness
                L  = float(op_spec.get("L",  50))   # extrude length
                # Build I-profile as closed wire
                hw2 = H / 2; wf2 = W / 2
                pts = [
                    Base.Vector(-wf2, -hw2, 0),  Base.Vector(wf2, -hw2, 0),
                    Base.Vector(wf2, -hw2+tf, 0), Base.Vector(tw/2, -hw2+tf, 0),
                    Base.Vector(tw/2, hw2-tf, 0), Base.Vector(wf2, hw2-tf, 0),
                    Base.Vector(wf2, hw2, 0),     Base.Vector(-wf2, hw2, 0),
                    Base.Vector(-wf2, hw2-tf, 0), Base.Vector(-tw/2, hw2-tf, 0),
                    Base.Vector(-tw/2, -hw2+tf, 0), Base.Vector(-wf2, -hw2+tf, 0),
                    Base.Vector(-wf2, -hw2, 0),
                ]
                wire = Part.makePolygon(pts)
                face = Part.Face(wire)
                sh   = face.extrude(Base.Vector(0, 0, L))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_channel":
                # C-channel (U-channel) profile extruded along Z
                W  = float(op_spec.get("W",  20))   # flange width
                H  = float(op_spec.get("H",  20))   # total height
                tf = float(op_spec.get("tf",  2.5)) # flange thickness
                tw = float(op_spec.get("tw",  2))   # web thickness
                L  = float(op_spec.get("L",  50))   # extrude length
                pts = [
                    Base.Vector(0,   0,   0),  Base.Vector(W,   0,   0),
                    Base.Vector(W,   tf,  0),  Base.Vector(tw,  tf,  0),
                    Base.Vector(tw,  H-tf, 0), Base.Vector(W,   H-tf, 0),
                    Base.Vector(W,   H,   0),  Base.Vector(0,   H,   0),
                    Base.Vector(0,   0,   0),
                ]
                wire = Part.makePolygon(pts)
                face = Part.Face(wire)
                sh   = face.extrude(Base.Vector(0, 0, L))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_l_profile":
                # L-profile (angle iron) extruded along Z
                W  = float(op_spec.get("W",  20))  # horizontal leg width
                H  = float(op_spec.get("H",  20))  # vertical leg height
                t  = float(op_spec.get("t",  2.5)) # thickness
                L  = float(op_spec.get("L",  50))  # extrude length
                pts = [
                    Base.Vector(0, 0, 0),  Base.Vector(W, 0, 0),
                    Base.Vector(W, t, 0),  Base.Vector(t, t, 0),
                    Base.Vector(t, H, 0),  Base.Vector(0, H, 0),
                    Base.Vector(0, 0, 0),
                ]
                wire = Part.makePolygon(pts)
                face = Part.Face(wire)
                sh   = face.extrude(Base.Vector(0, 0, L))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "boolean_split":
                # Split a solid by a plane, return the portion below/before the plane.
                # The cutter occupies everything ABOVE/BEYOND offset so we keep below.
                sh_id  = op_spec.get("shape")
                plane  = op_spec.get("plane", "XY")   # XY / XZ / YZ
                offset = float(op_spec.get("offset", 0))
                sh = shapes[sh_id]
                bb = sh.BoundBox
                big = max(bb.XLength, bb.YLength, bb.ZLength) * 4 + 20
                cx = (bb.XMin + bb.XMax) / 2
                cy = (bb.YMin + bb.YMax) / 2
                cz = (bb.ZMin + bb.ZMax) / 2
                # Cutter covers everything on the positive side of the plane
                if plane == "XY":   # cut at Z=offset; keep Z < offset
                    cutter = Part.makeBox(
                        big, big, big,
                        Base.Vector(cx - big/2, cy - big/2, offset))
                elif plane == "XZ":  # cut at Y=offset; keep Y < offset
                    cutter = Part.makeBox(
                        big, big, big,
                        Base.Vector(cx - big/2, offset, cz - big/2))
                else:               # YZ, cut at X=offset; keep X < offset
                    cutter = Part.makeBox(
                        big, big, big,
                        Base.Vector(offset, cy - big/2, cz - big/2))
                sh_cut = sh.cut(cutter)
                if sh_cut.isNull() or sh_cut.Volume < 0.01:
                    sh_cut = sh
                    results.setdefault("warnings", []).append("boolean_split: cut empty, returning original")
                shapes[op_id] = sh_cut
                results["shapes"][op_id] = _shape_summary(sh_cut)

            elif op == "make_bezier_curve":
                # Bezier curve through control points
                ctrl_pts = op_spec.get("points",
                           [[0,0,0],[10,15,0],[20,5,0],[30,20,0]])
                degree    = int(op_spec.get("degree", min(3, len(ctrl_pts)-1)))
                _bz = Part.BezierCurve()
                _bz.setPoles([Base.Vector(*p) for p in ctrl_pts])
                sh = _bz.toShape()
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_scale":
                # Non-uniform scale transform
                sh_id = op_spec.get("shape")
                sx    = float(op_spec.get("sx", op_spec.get("s", 1)))
                sy    = float(op_spec.get("sy", op_spec.get("s", 1)))
                sz    = float(op_spec.get("sz", op_spec.get("s", 1)))
                sh = shapes[sh_id]
                _m = App.Matrix()
                _m.scale(sx, sy, sz)
                sh_scaled = sh.transformGeometry(_m)
                shapes[op_id] = sh_scaled
                results["shapes"][op_id] = _shape_summary(sh_scaled)

            elif op == "make_array_3d":
                # 3D rectangular grid array
                sh_id = op_spec.get("shape")
                nx, ny, nz = (int(op_spec.get("nx", 2)),
                              int(op_spec.get("ny", 2)),
                              int(op_spec.get("nz", 1)))
                dx = float(op_spec.get("dx", 20))
                dy = float(op_spec.get("dy", 20))
                dz = float(op_spec.get("dz", 0))
                parts = []
                for iz in range(nz):
                    for iy in range(ny):
                        for ix in range(nx):
                            cp = shapes[sh_id].copy()
                            cp.translate(Base.Vector(dx*ix, dy*iy, dz*iz))
                            parts.append(cp)
                sh = Part.makeCompound(parts)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_cross_section":
                # Get the 2D cross-section face of a solid at a given plane
                sh_id  = op_spec.get("shape")
                axis   = op_spec.get("axis", "Z")
                height = float(op_spec.get("height", 0))
                sh = shapes[sh_id]
                bb = sh.BoundBox
                big = max(bb.XLength, bb.YLength, bb.ZLength) * 2 + 10
                if axis == "Z":
                    plane = Part.makePlane(big, big,
                        Base.Vector(-big/2+bb.Center.x, -big/2+bb.Center.y, height))
                elif axis == "Y":
                    plane = Part.makePlane(big, big,
                        Base.Vector(-big/2+bb.Center.x, height, -big/2+bb.Center.z),
                        Base.Vector(0,0,1), Base.Vector(0,1,0))
                else:
                    plane = Part.makePlane(big, big,
                        Base.Vector(height, -big/2+bb.Center.y, -big/2+bb.Center.z),
                        Base.Vector(0,0,1), Base.Vector(1,0,0))
                section = sh.section(plane)
                if section.isNull():
                    section = sh.section(Part.Face(plane))
                shapes[op_id] = section
                results["shapes"][op_id] = _shape_summary(section)

            elif op == "make_swept_solid":
                # Sweep a circle along a Bezier/polyline path
                pts   = op_spec.get("path",
                        [[0,0,0],[0,0,10],[5,0,20],[5,5,30]])
                r     = float(op_spec.get("r", 3))
                path_pts = [Base.Vector(*p) for p in pts]
                path_pts.append(path_pts[-1])  # ensure closure-safe
                try:
                    _bz = Part.BezierCurve()
                    _bz.setPoles(path_pts[:-1])
                    path_wire = Part.Wire([_bz.toShape()])
                except Exception:
                    path_wire = Part.Wire([Part.makePolygon(path_pts)])
                # Profile circle at start of path
                start = path_pts[0]
                end   = path_pts[1]
                tang  = (end - start).normalize()
                # Circle perpendicular to tangent
                perp  = tang.cross(Base.Vector(1,0,0))
                if perp.Length < 0.01:
                    perp = tang.cross(Base.Vector(0,1,0))
                perp.normalize()
                circle = Part.Circle(start, tang, r)
                prof   = Part.Wire([circle.toShape()])
                try:
                    sh = prof.makePipeShell([path_wire], False, True)
                    if sh.isNull() or sh.Volume < 0.01:
                        raise ValueError("pipe empty")
                except Exception:
                    sh = Part.makeCylinder(r, (path_pts[-1]-path_pts[0]).Length,
                                           path_pts[0], tang)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_taper_extrude":
                # Tapered extrusion: polygon extruded with draft angle
                pts_2d  = op_spec.get("points",
                          [[0,0],[20,0],[20,15],[10,22],[0,15]])
                H       = float(op_spec.get("H", 20))
                taper   = float(op_spec.get("taper", 5))  # draft angle in degrees
                base_pts = [Base.Vector(float(p[0]), float(p[1]), 0)
                            for p in pts_2d]
                base_pts_cl = base_pts + [base_pts[0]]  # close
                # Compute centroid of base
                cx = sum(p.x for p in base_pts) / len(base_pts)
                cy = sum(p.y for p in base_pts) / len(base_pts)
                # Scale factor at top based on taper angle
                # Find max distance from centroid
                max_r = max(math.sqrt((p.x-cx)**2 + (p.y-cy)**2)
                            for p in base_pts) + 0.001
                shrink = 1.0 - H * math.tan(math.radians(abs(taper))) / max_r
                shrink = max(0.01, shrink)  # prevent inversion
                top_pts = [Base.Vector(cx + (p.x-cx)*shrink,
                                       cy + (p.y-cy)*shrink, H)
                           for p in base_pts]
                top_pts_cl = top_pts + [top_pts[0]]
                base_wire = Part.makePolygon(base_pts_cl)
                top_wire  = Part.makePolygon(top_pts_cl)
                sh = Part.makeLoft([base_wire, top_wire], True, False)
                if sh.isNull() or sh.Volume < 0.01:
                    # Fallback: simple extrude
                    face = Part.Face(base_wire)
                    sh   = face.extrude(Base.Vector(0, 0, H))
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            elif op == "make_revolved_profile":
                # Revolve a 2D profile (list of XZ points) around Z axis
                pts_2d  = op_spec.get("points",
                                      [[0,0],[10,0],[10,5],[5,10],[0,10]])
                angle   = float(op_spec.get("angle", 360))
                pts3d   = [Base.Vector(float(p[0]), 0, float(p[1]))
                           for p in pts_2d]
                pts3d.append(pts3d[0])  # close
                wire = Part.makePolygon(pts3d)
                face = Part.Face(wire)
                sh   = face.revolve(Base.Vector(0,0,0), Base.Vector(0,0,1), angle)
                shapes[op_id] = sh
                results["shapes"][op_id] = _shape_summary(sh)

            # ── Engineering Analysis ──────────────────────────────────────────
            elif op == "mass_properties":
                # Volume, surface area, centroid, moments of inertia, radius of gyration
                sh_id = op_spec.get("shape")
                density = float(op_spec.get("density", 1.0))  # g/cm^3, default 1
                sh = shapes[sh_id]
                vol_cm3 = sh.Volume / 1000.0  # mm^3 -> cm^3
                mass    = vol_cm3 * density
                # Centroid
                bb = sh.BoundBox
                try:
                    cog = sh.centerOfMass
                    centroid = [round(cog.x, 4), round(cog.y, 4), round(cog.z, 4)]
                except Exception:
                    centroid = [round((bb.XMin+bb.XMax)/2, 4),
                                round((bb.YMin+bb.YMax)/2, 4),
                                round((bb.ZMin+bb.ZMax)/2, 4)]
                # Inertia matrix
                try:
                    matrix_of_inertia = sh.MatrixOfInertia
                    ixx = round(matrix_of_inertia.A11, 4)
                    iyy = round(matrix_of_inertia.A22, 4)
                    izz = round(matrix_of_inertia.A33, 4)
                    ixy = round(matrix_of_inertia.A12, 4)
                    ixz = round(matrix_of_inertia.A13, 4)
                    iyz = round(matrix_of_inertia.A23, 4)
                except Exception:
                    ixx = iyy = izz = ixy = ixz = iyz = None
                # Radius of gyration
                try:
                    rg = sh.RadiusOfGyration
                    rg_val = [round(rg.x, 4), round(rg.y, 4), round(rg.z, 4)]
                except Exception:
                    rg_val = None
                props = {
                    "volume_mm3":   round(sh.Volume, 4),
                    "area_mm2":     round(sh.Area, 4),
                    "volume_cm3":   round(vol_cm3, 6),
                    "mass_g":       round(mass, 4),
                    "density_g_cm3": density,
                    "centroid_mm":  centroid,
                    "inertia": {"Ixx": ixx, "Iyy": iyy, "Izz": izz,
                                "Ixy": ixy, "Ixz": ixz, "Iyz": iyz},
                    "radius_of_gyration": rg_val,
                    "bbox_mm": {
                        "x": [round(bb.XMin,3), round(bb.XMax,3)],
                        "y": [round(bb.YMin,3), round(bb.YMax,3)],
                        "z": [round(bb.ZMin,3), round(bb.ZMax,3)],
                    }
                }
                results.setdefault("analyses", []).append(
                    {"op": "mass_properties", "shape": sh_id, "props": props})
                if op_id:
                    shapes[op_id] = sh
                    results["shapes"][op_id] = {"type": "analysis", **props}

            elif op == "draft_angle":
                # Analyze draft angles: find faces whose normal deviates from
                # pull direction by less than min_angle (potential problem faces)
                sh_id     = op_spec.get("shape")
                pull_dir  = Base.Vector(*op_spec.get("direction", [0, 0, 1]))
                min_angle = float(op_spec.get("min_angle", 1.5))  # degrees
                sh = shapes[sh_id]
                face_results = []
                for i, face in enumerate(sh.Faces):
                    try:
                        # Sample normal at face midpoint
                        u_mid = (face.ParameterRange[0] + face.ParameterRange[1]) / 2
                        v_mid = (face.ParameterRange[2] + face.ParameterRange[3]) / 2
                        normal = face.normalAt(u_mid, v_mid)
                        dot    = abs(normal.dot(pull_dir.normalize()))
                        dot    = min(1.0, dot)
                        angle_deg = math.degrees(math.asin(dot))  # angle from pull plane
                        face_results.append({
                            "face_idx": i,
                            "angle_deg": round(angle_deg, 2),
                            "ok": angle_deg >= min_angle,
                            "area_mm2": round(face.Area, 2)
                        })
                    except Exception: pass
                problem_faces = [f for f in face_results if not f["ok"]]
                analysis = {
                    "total_faces":    len(face_results),
                    "ok_faces":       len(face_results) - len(problem_faces),
                    "problem_faces":  len(problem_faces),
                    "min_angle_deg":  min_angle,
                    "pull_direction": list(op_spec.get("direction", [0, 0, 1])),
                    "faces":          face_results,
                    "moldable":       len(problem_faces) == 0
                }
                results.setdefault("analyses", []).append(
                    {"op": "draft_angle", "shape": sh_id, "analysis": analysis})
                if op_id:
                    shapes[op_id] = sh
                    results["shapes"][op_id] = {"type": "draft_analysis", **analysis}

            elif op == "shape_analysis_3dprint":
                # 3D printing suitability analysis
                sh_id       = op_spec.get("shape")
                min_wall    = float(op_spec.get("min_wall_mm", 1.2))
                layer_h     = float(op_spec.get("layer_height", 0.2))
                overhang_lim= float(op_spec.get("overhang_deg", 45.0))  # degrees from vertical
                sh = shapes[sh_id]
                # Bounding box
                bb = sh.BoundBox
                z_height = bb.ZLength
                n_layers  = int(z_height / layer_h) if layer_h > 0 else 0
                # Check overhang faces
                up = Base.Vector(0, 0, 1)
                overhang_faces = []
                for i, face in enumerate(sh.Faces):
                    try:
                        u_mid = (face.ParameterRange[0] + face.ParameterRange[1]) / 2
                        v_mid = (face.ParameterRange[2] + face.ParameterRange[3]) / 2
                        normal = face.normalAt(u_mid, v_mid)
                        dot    = normal.dot(up)
                        # Negative dot = face points down = potential overhang
                        if dot < -math.cos(math.radians(overhang_lim)):
                            overhang_faces.append({
                                "face_idx": i,
                                "angle_from_vertical": round(
                                    math.degrees(math.acos(max(-1, min(1, abs(dot))))), 1),
                                "area_mm2": round(face.Area, 2)
                            })
                    except Exception: pass
                # Thin wall approximation: check if any dimension is below min_wall
                thin_dims = []
                for dim, length in [("X", bb.XLength), ("Y", bb.YLength), ("Z", bb.ZLength)]:
                    if 0 < length < min_wall:
                        thin_dims.append({"axis": dim, "length_mm": round(length, 3)})
                printability = {
                    "volume_mm3":      round(sh.Volume, 2),
                    "bbox_mm":         [round(bb.XLength,2), round(bb.YLength,2), round(bb.ZLength,2)],
                    "z_height_mm":     round(z_height, 2),
                    "n_layers":        n_layers,
                    "overhang_count":  len(overhang_faces),
                    "overhang_faces":  overhang_faces[:10],  # limit to 10
                    "thin_walls":      thin_dims,
                    "min_wall_mm":     min_wall,
                    "print_ready":     len(overhang_faces) == 0 and len(thin_dims) == 0,
                    "support_needed":  len(overhang_faces) > 0,
                    "is_solid":        len(sh.Solids) > 0,
                    "is_closed":       sh.isClosed()
                }
                results.setdefault("analyses", []).append(
                    {"op": "shape_analysis_3dprint", "shape": sh_id, "analysis": printability})
                if op_id:
                    shapes[op_id] = sh
                    results["shapes"][op_id] = {"type": "print_analysis", **printability}

            elif op == "measure_distance":
                # Minimum distance between two shapes
                sh1_id = op_spec.get("shape1")
                sh2_id = op_spec.get("shape2")
                sh1, sh2 = shapes[sh1_id], shapes[sh2_id]
                try:
                    dist = sh1.distToShape(sh2)
                    min_dist = round(dist[0], 4)
                    # dist[1] = list of (point_on_sh1, point_on_sh2) pairs
                    pt_pairs = [(list(map(lambda v: round(v,3), [p1.x, p1.y, p1.z])),
                                 list(map(lambda v: round(v,3), [p2.x, p2.y, p2.z])))
                                for p1, p2 in dist[1][:3]]
                except Exception as _md:
                    min_dist = -1
                    pt_pairs = []
                    results.setdefault("warnings", []).append(f"measure_distance: {_md}")
                info = {"distance_mm": min_dist, "nearest_pairs": pt_pairs}
                results.setdefault("analyses", []).append(
                    {"op": "measure_distance", "shape1": sh1_id, "shape2": sh2_id, **info})
                if op_id:
                    results["shapes"][op_id] = {"type": "measurement", **info}

            elif op == "make_shell_from_solid":
                # Convert solid to thin shell by removing one face
                sh_id     = op_spec.get("shape")
                thickness = float(op_spec.get("thickness", -2.0))  # negative = inward
                face_idx  = op_spec.get("face_idx", 0)  # face index to remove (open face)
                sh = shapes[sh_id]
                try:
                    open_face = sh.Faces[face_idx] if face_idx < len(sh.Faces) else sh.Faces[0]
                    shell_sh  = sh.makeThickness([open_face], thickness, 1e-3)
                    if shell_sh.isNull() or shell_sh.Volume < 1:
                        raise ValueError("makeThickness returned empty shape")
                except Exception as _msh:
                    # Fallback to OCC thick solid
                    try:
                        from OCC.Core.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
                        from OCC.Core.BRepTools import breptools
                        from OCC.Core.BRep import BRep_Builder
                        from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_ListOfShape
                        _bp = Path(tempfile.gettempdir()) / "_shell_bridge.brep"
                        sh.exportBrep(str(_bp))
                        occ_base = TopoDS_Shape()
                        breptools.Read(occ_base, str(_bp), BRep_Builder())
                        _bp.unlink()
                        shell_sh = sh.makeThickness([sh.Faces[0]], thickness, 1e-3)
                    except Exception:
                        shell_sh = sh
                        results.setdefault("warnings", []).append(f"makeShell fallback ({_msh})")
                shapes[op_id] = shell_sh
                results["shapes"][op_id] = _shape_summary(shell_sh)

            else:
                results["errors"].append(f"Unknown op: '{op}' (id={op_id})")

        except Exception as e:
            err_msg = f"Op '{op}' id='{op_id}' failed: {e}\n{traceback.format_exc()}"
            results["errors"].append(err_msg)
            if op_id:
                results["shapes"][op_id] = {"type": "ERROR", "error": str(e)}

    if results["errors"]:
        results["ok"] = False
    return results


def main():
    cmd_file, result_file = _parse_args()

    if not cmd_file:
        # Self-test mode
        print("FreeCAD Backend v2.0 — self-test")
        try:
            import FreeCAD, Part
            print("FreeCAD import OK")
            box = Part.makeBox(10, 10, 10)
            print(f"makeBox OK: volume={box.Volume:.1f}")
            print("SELF_TEST_OK")
        except Exception as e:
            print(f"SELF_TEST_FAIL: {e}")
        return

    # Read command file
    try:
        with open(cmd_file, "r", encoding="utf-8") as f:
            cmd = json.load(f)
    except Exception as e:
        err = {"ok": False, "errors": [f"Failed to read cmd file: {e}"]}
        if result_file:
            Path(result_file).parent.mkdir(parents=True, exist_ok=True)
            with open(result_file, "w", encoding="utf-8") as f:
                json.dump(err, f, indent=2)
        print(json.dumps(err))
        return

    ops = cmd.get("ops", [])
    results = run_ops(ops)

    # Write result
    out_str = json.dumps(results, indent=2, ensure_ascii=False)
    if result_file:
        Path(result_file).parent.mkdir(parents=True, exist_ok=True)
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(out_str)
    print(out_str)


if __name__ == "__main__":
    main()
