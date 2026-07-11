#!/usr/bin/env python3
"""
FreeCAD Model Builder v2.0 — AI驱动的完整建模流水线

运行在系统Python，通过freecadcmd调用freecad_backend.py

API:
  builder = FCModelBuilder()
  result  = builder.build("enclosure", {"L":50,"W":40,"H":30,"wall":2})
  result  = builder.build("hex_bolt",  {"diameter":8,"length":30})
  result  = builder.run_ops([{"op":"make_box","id":"b","L":20,"W":10,"H":5},
                              {"op":"export_stl","shape":"b","path":"out.stl"}])

CLI:
  python fc_model_builder.py box --L 20 --W 10 --H 5 --out out.stl
  python fc_model_builder.py build enclosure --params '{"L":50,"W":40}'
  python fc_model_builder.py test
"""

import os, sys, json, subprocess, tempfile, time, shutil, math, argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

SCRIPT_DIR   = Path(__file__).parent.resolve()

# ═══ 万法归一 · 路径引导 ════════════════════════════════════════════
_DAO_ROOT = next((p for p in Path(__file__).resolve().parents
                  if (p / '_paths.py').is_file()), SCRIPT_DIR.parent)
if str(_DAO_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAO_ROOT))
import _paths as _dao_paths  # noqa: F401  (registers 五层 sys.path)
ROOT_DIR = _DAO_ROOT
# ═══════════════════════════════════════════════════════════════════

BACKEND_SCRIPT = SCRIPT_DIR / "freecad_backend.py"   # 同层 10-反笙_FreeCAD

FREECAD_CMDS = [
    r"D:\安装的软件\FreeCAD 1.0\bin\freecadcmd.exe",
    r"D:\安装的软件\FreeCAD 0.21\bin\FreeCADCmd.exe",
    r"C:\Program Files\FreeCAD 1.0\bin\freecadcmd.exe",
    r"C:\Program Files\FreeCAD\bin\FreeCADCmd.exe",
]
_NO_WINDOW = 0x08000000

OUTPUT_DIR = _dao_paths.PROJECTS / "fc_output"


# ─────────────────────────────────────────────────────────────────────────────
# Core executor
# ─────────────────────────────────────────────────────────────────────────────

class FCModelBuilder:
    def __init__(self, freecad_cmd: str = None, timeout: int = 300):
        self.cmd = freecad_cmd or self._find_cmd()
        self.timeout = timeout
        self.output_dir = OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _find_cmd(self) -> Optional[str]:
        for p in FREECAD_CMDS:
            if Path(p).exists():
                return p
        return shutil.which("freecadcmd") or shutil.which("FreeCADCmd")

    def available(self) -> bool:
        return self.cmd is not None and Path(self.cmd).exists()

    def run_ops(self, ops: List[Dict], label: str = "ops") -> Dict:
        """
        Execute FreeCAD operations via freecadcmd subprocess.

        freecadcmd only accepts a single script path — no custom args.
        Solution: generate a self-contained launcher .py in a pure-ASCII
        temp directory that embeds the ops JSON and result path inline.
        """
        if not self.available():
            return {"ok": False, "error": "FreeCAD not found", "ops_count": len(ops)}

        t0 = time.time()
        # Use system temp dir which is guaranteed ASCII-safe
        import uuid
        tmp_base = Path(tempfile.gettempdir()) / f"fcb_{uuid.uuid4().hex[:8]}"
        tmp_base.mkdir(parents=True, exist_ok=True)
        try:
            cmd_file    = tmp_base / "cmd.json"
            result_file = tmp_base / "result.json"
            backend_tmp = tmp_base / "freecad_backend.py"
            launcher    = tmp_base / "launcher.py"

            # Copy backend (no Chinese path inside FreeCAD's Python)
            shutil.copy2(str(BACKEND_SCRIPT), str(backend_tmp))

            # Write ops as JSON
            cmd_file.write_text(
                json.dumps({"ops": ops}, indent=2, ensure_ascii=True),
                encoding="utf-8"
            )

            # Build self-contained launcher script
            # All paths use raw strings (forward slashes to avoid escape issues)
            cmd_path_str    = str(cmd_file).replace("\\", "/")
            result_path_str = str(result_file).replace("\\", "/")
            backend_dir_str = str(tmp_base).replace("\\", "/")

            launcher_code = f'''import sys, json
sys.path.insert(0, r"{backend_dir_str}")
from freecad_backend import run_ops
with open(r"{cmd_path_str}", "r", encoding="utf-8") as _f:
    _cmd = json.load(_f)
_result = run_ops(_cmd.get("ops", []))
with open(r"{result_path_str}", "w", encoding="utf-8") as _f:
    json.dump(_result, _f, indent=2, ensure_ascii=False)
print("FC_DONE")
'''
            launcher.write_text(launcher_code, encoding="utf-8")

            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            r = subprocess.run(
                [self.cmd, str(launcher)],
                capture_output=True,
                timeout=self.timeout,
                startupinfo=si,
                creationflags=_NO_WINDOW,
            )
            elapsed = round(time.time() - t0, 2)
            stdout = (r.stdout or b"").decode("utf-8", errors="replace").strip()
            stderr = (r.stderr or b"").decode("utf-8", errors="replace").strip()

            if result_file.exists():
                try:
                    result = json.loads(result_file.read_text(encoding="utf-8"))
                    result["elapsed_s"] = elapsed
                    result["label"] = label
                    return result
                except json.JSONDecodeError as e:
                    return {"ok": False, "error": f"Bad JSON in result: {e}",
                            "stdout": stdout[:500], "stderr": stderr[:500],
                            "elapsed_s": elapsed, "label": label}

            # No result file — parse stdout
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        result = json.loads(line)
                        result["elapsed_s"] = elapsed
                        result["label"] = label
                        return result
                    except Exception:
                        pass

            return {
                "ok": False,
                "error": "No result file produced",
                "returncode": r.returncode,
                "stdout": stdout[:1000],
                "stderr": stderr[:500],
                "elapsed_s": elapsed,
                "label": label,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Timeout after {self.timeout}s", "label": label}
        except Exception as e:
            return {"ok": False, "error": str(e), "label": label}
        finally:
            shutil.rmtree(str(tmp_base), ignore_errors=True)

    def analyze_stl(self, stl_path: str) -> Dict:
        """Run trimesh analysis on an STL file."""
        try:
            import trimesh
            import numpy as np
            mesh = trimesh.load(str(stl_path))
            bb = mesh.bounding_box.extents
            result = {
                "ok": True,
                "file": str(stl_path),
                "size_bytes": Path(stl_path).stat().st_size,
                "vertices": len(mesh.vertices),
                "faces": len(mesh.faces),
                "is_watertight": bool(mesh.is_watertight),
                "volume_mm3": round(float(mesh.volume), 3) if mesh.is_watertight else None,
                "surface_area_mm2": round(float(mesh.area), 3),
                "bounds_mm": [round(float(b), 3) for b in bb],
                "centroid_mm": [round(float(c), 3) for c in mesh.centroid],
            }
            if mesh.is_watertight:
                result["mass_g_pla"] = round(float(mesh.volume) * 1.24e-3, 2)
            return result
        except ImportError:
            return {"ok": False, "error": "trimesh not installed"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _make_output_paths(self, name: str, formats: List[str] = None) -> Dict[str, str]:
        """Generate output file paths for a model."""
        if formats is None:
            formats = ["stl", "step"]
        ts = int(time.time())
        base = self.output_dir / f"{name}_{ts}"
        paths = {}
        for fmt in formats:
            paths[fmt] = str(base.with_suffix(f".{fmt}"))
        return paths

    # ─────────────────────────────────────────────────────────────────────
    # Complete parametric model library
    # ─────────────────────────────────────────────────────────────────────

    def build(self, model_type: str, params: Dict = None, out_dir: str = None,
              formats: List[str] = None) -> Dict:
        """Build a parametric model by type name."""
        if params is None:
            params = {}
        if out_dir:
            self.output_dir = Path(out_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        if formats is None:
            formats = ["stl", "step"]

        builders = {
            "box":           self._build_box,
            "rounded_box":   self._build_rounded_box,
            "cylinder":      self._build_cylinder,
            "sphere":        self._build_sphere,
            "cone":          self._build_cone,
            "torus":         self._build_torus,
            "tube":          self._build_tube,
            "hex_bolt":      self._build_hex_bolt,
            "hex_nut":       self._build_hex_nut,
            "washer":        self._build_washer,
            "bracket":       self._build_bracket,
            "enclosure":     self._build_enclosure,
            "gear_spur":     self._build_gear_spur,
            "bearing_seat":  self._build_bearing_seat,
            "slot":          self._build_slot,
            "pipe":          self._build_pipe,
            "flange":        self._build_flange,
            "t_slot":        self._build_t_slot,
            "motor_mount":   self._build_motor_mount,
            "standoff":      self._build_standoff,
            "cable_clamp":   self._build_cable_clamp,
            "hinge":         self._build_hinge,
            "spring":        self._build_spring,
            "chamfer_box":   self._build_chamfer_box,
            "shaft":          self._build_shaft,
            "bushing":        self._build_bushing,
            "hex_socket_bolt": self._build_hex_socket_bolt,
            "knob":           self._build_knob,
            "lug":            self._build_lug,
            "custom_ops":    self._build_custom_ops,
        }

        fn = builders.get(model_type.lower())
        if fn is None:
            return {"ok": False, "error": f"Unknown model type: '{model_type}'. Available: {list(builders.keys())}"}

        ops, paths = fn(params, formats)
        result = self.run_ops(ops, label=model_type)
        result["model_type"] = model_type
        result["params"] = params
        result["output_files"] = paths

        # Verify outputs + analyze STL
        for fmt, path in paths.items():
            if Path(path).exists() and Path(path).stat().st_size > 0:
                result[f"{fmt}_ok"] = True
                result[f"{fmt}_path"] = path
                result[f"{fmt}_size"] = Path(path).stat().st_size
            else:
                result[f"{fmt}_ok"] = False
                result["ok"] = False

        if paths.get("stl") and Path(paths["stl"]).exists():
            result["analysis"] = self.analyze_stl(paths["stl"])

        return result

    # ─────────────────────────────────────────────────────────────────────
    # Model builders — each returns (ops_list, output_paths_dict)
    # ─────────────────────────────────────────────────────────────────────

    def _build_box(self, p: Dict, formats: List[str]):
        L = float(p.get("L", p.get("length", 20)))
        W = float(p.get("W", p.get("width", 15)))
        H = float(p.get("H", p.get("height", 10)))
        pos = p.get("pos", [0, 0, 0])
        paths = self._make_output_paths("box", formats)
        ops = [{"op": "make_box", "id": "box", "L": L, "W": W, "H": H, "pos": pos}]
        ops += self._export_ops("box", paths)
        ops.append({"op": "shape_info", "shape": "box"})
        return ops, paths

    def _build_rounded_box(self, p: Dict, formats: List[str]):
        L = float(p.get("L", 30))
        W = float(p.get("W", 20))
        H = float(p.get("H", 10))
        R = float(p.get("R", p.get("fillet", 2)))
        paths = self._make_output_paths("rounded_box", formats)
        ops = [{"op": "make_rounded_box", "id": "rbox", "L": L, "W": W, "H": H, "R": R}]
        ops += self._export_ops("rbox", paths)
        ops.append({"op": "shape_info", "shape": "rbox"})
        return ops, paths

    def _build_cylinder(self, p: Dict, formats: List[str]):
        R = float(p.get("R", p.get("radius", 10)))
        H = float(p.get("H", p.get("height", 20)))
        pos = p.get("pos", [0, 0, 0])
        paths = self._make_output_paths("cylinder", formats)
        ops = [{"op": "make_cylinder", "id": "cyl", "R": R, "H": H, "pos": pos}]
        ops += self._export_ops("cyl", paths)
        ops.append({"op": "shape_info", "shape": "cyl"})
        return ops, paths

    def _build_sphere(self, p: Dict, formats: List[str]):
        R = float(p.get("R", p.get("radius", 10)))
        pos = p.get("pos", [0, 0, 0])
        paths = self._make_output_paths("sphere", formats)
        ops = [{"op": "make_sphere", "id": "sph", "R": R, "pos": pos}]
        ops += self._export_ops("sph", paths)
        ops.append({"op": "shape_info", "shape": "sph"})
        return ops, paths

    def _build_cone(self, p: Dict, formats: List[str]):
        R1 = float(p.get("R1", p.get("R_base", 10)))
        R2 = float(p.get("R2", p.get("R_top", 0)))
        H  = float(p.get("H", p.get("height", 20)))
        paths = self._make_output_paths("cone", formats)
        ops = [{"op": "make_cone", "id": "cone", "R1": R1, "R2": R2, "H": H}]
        ops += self._export_ops("cone", paths)
        return ops, paths

    def _build_torus(self, p: Dict, formats: List[str]):
        R1 = float(p.get("R1", p.get("major_r", 15)))
        R2 = float(p.get("R2", p.get("minor_r", 3)))
        paths = self._make_output_paths("torus", formats)
        ops = [{"op": "make_torus", "id": "tor", "R1": R1, "R2": R2}]
        ops += self._export_ops("tor", paths)
        return ops, paths

    def _build_tube(self, p: Dict, formats: List[str]):
        R_outer = float(p.get("R_outer", p.get("OD", 20)) / (2 if p.get("OD") else 1))
        R_inner = float(p.get("R_inner", p.get("ID", 16)) / (2 if p.get("ID") else 1))
        H = float(p.get("H", p.get("height", 30)))
        if "OD" in p:
            R_outer = float(p["OD"]) / 2
        if "ID" in p:
            R_inner = float(p["ID"]) / 2
        paths = self._make_output_paths("tube", formats)
        ops = [{"op": "make_tube", "id": "tube", "R_outer": R_outer, "R_inner": R_inner, "H": H}]
        ops += self._export_ops("tube", paths)
        return ops, paths

    def _build_hex_bolt(self, p: Dict, formats: List[str]):
        d       = float(p.get("diameter", p.get("d", 8)))
        length  = float(p.get("length", p.get("L", 30)))
        head_h  = float(p.get("head_h", d * 0.65))
        head_w  = float(p.get("head_w", d * 1.8))
        paths   = self._make_output_paths(f"bolt_M{int(d)}x{int(length)}", formats)
        ops = [{"op": "make_hex_bolt", "id": "bolt",
                "diameter": d, "length": length, "head_h": head_h, "head_w": head_w}]
        ops += self._export_ops("bolt", paths)
        ops.append({"op": "shape_info", "shape": "bolt"})
        return ops, paths

    def _build_hex_nut(self, p: Dict, formats: List[str]):
        d         = float(p.get("diameter", p.get("d", 8)))
        thickness = float(p.get("thickness", d * 0.8))
        head_w    = float(p.get("head_w", d * 1.8))
        paths     = self._make_output_paths(f"nut_M{int(d)}", formats)
        ops = [{"op": "make_hex_nut", "id": "nut",
                "diameter": d, "thickness": thickness, "head_w": head_w}]
        ops += self._export_ops("nut", paths)
        return ops, paths

    def _build_washer(self, p: Dict, formats: List[str]):
        d_inner = float(p.get("d_inner", p.get("ID", 8.4)))
        d_outer = float(p.get("d_outer", p.get("OD", 18)))
        h       = float(p.get("h", p.get("thickness", 1.5)))
        paths   = self._make_output_paths("washer", formats)
        ops = [
            {"op": "make_tube", "id": "washer",
             "R_outer": d_outer / 2, "R_inner": d_inner / 2, "H": h},
        ]
        ops += self._export_ops("washer", paths)
        return ops, paths

    def _build_bracket(self, p: Dict, formats: List[str]):
        W      = float(p.get("W", p.get("width", 30)))
        H      = float(p.get("H", p.get("height", 30)))
        D      = float(p.get("D", p.get("thickness", 5)))
        fillet = float(p.get("fillet", 2))
        paths  = self._make_output_paths("bracket", formats)
        ops = [{"op": "make_bracket", "id": "bkt", "W": W, "H": H, "D": D, "fillet": fillet}]
        ops += self._export_ops("bkt", paths)
        return ops, paths

    def _build_enclosure(self, p: Dict, formats: List[str]):
        L        = float(p.get("L", p.get("length", 60)))
        W        = float(p.get("W", p.get("width", 40)))
        H        = float(p.get("H", p.get("height", 30)))
        wall     = float(p.get("wall", p.get("t", 2.0)))
        open_top = bool(p.get("open_top", True))
        paths    = self._make_output_paths("enclosure", formats)
        ops = [{"op": "make_enclosure", "id": "enc",
                "L": L, "W": W, "H": H, "wall": wall, "open_top": open_top}]
        # Optional mounting holes
        if p.get("mount_holes", False):
            hole_d = float(p.get("hole_d", 3.0))
            margin = float(p.get("hole_margin", 5.0))
            hole_positions = [
                [margin, margin, 0],
                [L - margin, margin, 0],
                [margin, W - margin, 0],
                [L - margin, W - margin, 0],
            ]
            for i, hpos in enumerate(hole_positions):
                ops.append({"op": "make_cylinder", "id": f"hole{i}",
                            "R": hole_d / 2, "H": wall + 2, "pos": [hpos[0], hpos[1], -1]})
            hole_ids = [f"hole{i}" for i in range(4)]
            ops.append({"op": "cut", "id": "enc_final", "base": "enc",
                        "tools": hole_ids})
            export_shape = "enc_final"
        else:
            export_shape = "enc"
        ops += self._export_ops(export_shape, paths)
        ops.append({"op": "shape_info", "shape": export_shape})
        return ops, paths

    def _build_gear_spur(self, p: Dict, formats: List[str]):
        teeth  = int(p.get("teeth", p.get("z", 20)))
        module = float(p.get("module", p.get("m", 1.0)))
        width  = float(p.get("width", p.get("b", 10)))
        hub_r  = float(p.get("hub_r", p.get("bore", 0)) / 2 if "bore" in p else p.get("hub_r", 0))
        paths  = self._make_output_paths(f"gear_z{teeth}_m{module}", formats)
        ops = [{"op": "make_gear_spur", "id": "gear",
                "teeth": teeth, "module": module, "width": width, "hub_r": hub_r}]
        ops += self._export_ops("gear", paths)
        ops.append({"op": "shape_info", "shape": "gear"})
        return ops, paths

    def _build_bearing_seat(self, p: Dict, formats: List[str]):
        od   = float(p.get("od", p.get("OD", 40)))
        bore = float(p.get("bore", p.get("ID", 17)))
        W    = float(p.get("W", p.get("width", 12)))
        paths = self._make_output_paths("bearing_seat", formats)
        ops = [{"op": "make_bearing_seat", "id": "seat", "od": od, "bore": bore, "W": W}]
        ops += self._export_ops("seat", paths)
        return ops, paths

    def _build_slot(self, p: Dict, formats: List[str]):
        L = float(p.get("L", 20))
        W = float(p.get("W", 8))
        H = float(p.get("H", 5))
        paths = self._make_output_paths("slot", formats)
        ops = [{"op": "make_slot", "id": "slot", "L": L, "W": W, "H": H}]
        ops += self._export_ops("slot", paths)
        return ops, paths

    def _build_pipe(self, p: Dict, formats: List[str]):
        R_outer = float(p.get("R_outer", 10))
        R_inner = float(p.get("R_inner", 8))
        H       = float(p.get("H", 50))
        # Could also add bends, but basic pipe = tube
        return self._build_tube({"R_outer": R_outer, "R_inner": R_inner, "H": H}, formats)

    def _build_flange(self, p: Dict, formats: List[str]):
        od    = float(p.get("od", 60))
        bore  = float(p.get("bore", 20))
        H     = float(p.get("H", 8))
        n_holes = int(p.get("n_holes", 4))
        hole_r  = float(p.get("hole_r", 3))
        pcd     = float(p.get("pcd", 45))  # pitch circle diameter
        paths   = self._make_output_paths("flange", formats)
        ops = [
            {"op": "make_cylinder", "id": "body",  "R": od / 2,   "H": H},
            {"op": "make_cylinder", "id": "cbore", "R": bore / 2, "H": H},
            {"op": "cut", "id": "ring", "base": "body", "tools": ["cbore"]},
        ]
        for i in range(n_holes):
            angle = 2 * math.pi * i / n_holes
            hx = (pcd / 2) * math.cos(angle)
            hy = (pcd / 2) * math.sin(angle)
            ops.append({"op": "make_cylinder", "id": f"fh{i}",
                        "R": hole_r, "H": H, "pos": [hx, hy, 0]})
        tool_ids = [f"fh{i}" for i in range(n_holes)]
        ops.append({"op": "cut", "id": "flange", "base": "ring", "tools": tool_ids})
        ops += self._export_ops("flange", paths)
        ops.append({"op": "shape_info", "shape": "flange"})
        return ops, paths

    def _build_t_slot(self, p: Dict, formats: List[str]):
        W  = float(p.get("W", 20))  # outer width
        H  = float(p.get("H", 20))  # outer height
        L  = float(p.get("L", 100)) # length
        slot_w = float(p.get("slot_w", 6))   # T-slot opening
        slot_h = float(p.get("slot_h", 8))   # T-slot depth
        paths = self._make_output_paths("t_slot_extrusion", formats)
        ops = [
            {"op": "make_box", "id": "body", "L": W, "W": H, "H": L},
            # Center bore
            {"op": "make_cylinder", "id": "cbore", "R": 4.2,
             "H": L, "pos": [W/2, H/2, 0], "axis": [0, 0, 1]},
            {"op": "cut", "id": "body2", "base": "body", "tools": ["cbore"]},
            # 4 T-slots (one per side)
            {"op": "make_slot", "id": "slot_top",
             "L": L, "W": slot_w, "H": slot_h},
        ]
        ops += self._export_ops("body2", paths)
        return ops, paths

    def _build_motor_mount(self, p: Dict, formats: List[str]):
        nema = int(p.get("nema", 17))
        thickness = float(p.get("thickness", 3))
        nema_dims = {17: 42.3, 23: 57.0, 11: 28.2}
        side = nema_dims.get(nema, 42.3)
        hole_pcd = side - 10
        shaft_d  = 5.0 if nema == 17 else 8.0
        n_mount  = 4
        paths    = self._make_output_paths(f"motor_mount_nema{nema}", formats)
        ops = [
            {"op": "make_box", "id": "plate",
             "L": side + 10, "W": side + 10, "H": thickness,
             "pos": [-(side + 10) / 2, -(side + 10) / 2, 0]},
            {"op": "make_cylinder", "id": "shaft_hole",
             "R": (shaft_d + 0.5) / 2, "H": thickness},
        ]
        for i in range(n_mount):
            angle = math.pi / 4 + math.pi / 2 * i
            hx = (hole_pcd / 2) * math.cos(angle)
            hy = (hole_pcd / 2) * math.sin(angle)
            ops.append({"op": "make_cylinder", "id": f"mh{i}",
                        "R": 1.5, "H": thickness, "pos": [hx, hy, 0]})
        tool_ids = ["shaft_hole"] + [f"mh{i}" for i in range(n_mount)]
        ops.append({"op": "cut", "id": "mount", "base": "plate", "tools": tool_ids})
        ops += self._export_ops("mount", paths)
        return ops, paths

    def _build_standoff(self, p: Dict, formats: List[str]):
        od = float(p.get("od", 6))
        id_ = float(p.get("id", 3.2))
        H   = float(p.get("H", 10))
        paths = self._make_output_paths("standoff", formats)
        ops = [{"op": "make_tube", "id": "stoff",
                "R_outer": od / 2, "R_inner": id_ / 2, "H": H}]
        ops += self._export_ops("stoff", paths)
        return ops, paths

    def _build_cable_clamp(self, p: Dict, formats: List[str]):
        cable_d = float(p.get("cable_d", p.get("d", 5)))
        W       = float(p.get("W", 20))
        H       = float(p.get("H", 10))
        t       = float(p.get("t", 2))
        paths   = self._make_output_paths("cable_clamp", formats)
        body_H  = cable_d + 2 * t
        ops = [
            {"op": "make_box", "id": "body", "L": W, "W": body_H, "H": H},
            {"op": "make_cylinder", "id": "channel",
             "R": cable_d / 2, "H": W,
             "pos": [0, body_H / 2, H / 2], "axis": [1, 0, 0]},
            {"op": "cut", "id": "clamp", "base": "body", "tools": ["channel"]},
        ]
        ops += self._export_ops("clamp", paths)
        return ops, paths

    def _build_hinge(self, p: Dict, formats: List[str]):
        W     = float(p.get("W", 30))
        H     = float(p.get("H", 30))
        t     = float(p.get("t", 2))
        pin_r = float(p.get("pin_r", 2))
        paths = self._make_output_paths("hinge_leaf", formats)
        # One hinge leaf
        ops = [
            {"op": "make_box", "id": "leaf", "L": W, "W": H, "H": t},
            # Knuckle cylinder
            {"op": "make_cylinder", "id": "knuckle", "R": pin_r * 1.5,
             "H": H / 2, "pos": [W / 2, 0, t / 2], "axis": [0, 1, 0]},
            {"op": "fuse", "id": "hinge", "shapes": ["leaf", "knuckle"]},
        ]
        ops += self._export_ops("hinge", paths)
        return ops, paths

    def _build_spring(self, p: Dict, formats: List[str]):
        R     = float(p.get("R", 10))
        wire  = float(p.get("wire_r", 1.5))
        pitch = float(p.get("pitch", 8))
        turns = float(p.get("turns", 5))
        paths = self._make_output_paths("spring", formats)
        ops = [{"op": "make_spring", "id": "spring",
                "R": R, "wire_r": wire, "pitch": pitch, "turns": turns}]
        ops += self._export_ops("spring", paths)
        return ops, paths

    def _build_chamfer_box(self, p: Dict, formats: List[str]):
        L = float(p.get("L", 30))
        W = float(p.get("W", 20))
        H = float(p.get("H", 15))
        c = float(p.get("chamfer", 2.0))
        paths = self._make_output_paths("chamfer_box", formats)
        ops = [{"op": "make_chamfer_box", "id": "cbox",
                "L": L, "W": W, "H": H, "chamfer": c}]
        ops += self._export_ops("cbox", paths)
        return ops, paths

    def _build_shaft(self, p: Dict, formats: List[str]):
        D   = float(p.get("D",  12))   # shaft diameter
        L   = float(p.get("L",  60))   # shaft length
        key = p.get("keyway", True)    # include keyway
        kw  = float(p.get("kw", D*0.25)) # key width
        kh  = float(p.get("kh", D*0.14)) # key depth
        paths = self._make_output_paths("shaft", formats)
        ops = [
            {"op": "make_cylinder", "id": "sh", "R": D/2, "H": L},
        ]
        if key:
            ops += [
                {"op": "make_box", "id": "kslot",
                 "L": L, "W": kw, "H": kh,
                 "pos": [0, -kw/2, D/2 - kh]},
                {"op": "cut", "id": "sh", "base": "sh", "tools": ["kslot"]},
            ]
        ops += self._export_ops("sh", paths)
        ops.append({"op": "shape_info", "shape": "sh"})
        return ops, paths

    def _build_bushing(self, p: Dict, formats: List[str]):
        D_out = float(p.get("D_out", 20))  # outer diameter
        D_in  = float(p.get("D_in",  12))  # bore diameter
        L     = float(p.get("L",  20))
        paths = self._make_output_paths("bushing", formats)
        ops = [
            {"op": "make_hollow_cylinder", "id": "bu",
             "R_out": D_out/2, "R_in": D_in/2, "H": L},
        ]
        ops += self._export_ops("bu", paths)
        ops.append({"op": "shape_info", "shape": "bu"})
        return ops, paths

    def _build_hex_socket_bolt(self, p: Dict, formats: List[str]):
        import math as _m
        d  = float(p.get("d",  8))    # thread diameter
        L  = float(p.get("L",  30))   # total length
        hd = float(p.get("hd", d*1.5)) # head diameter
        hh = float(p.get("hh", d))    # head height
        sk = float(p.get("sk", d*0.6)) # hex socket width across flats
        paths = self._make_output_paths("hex_socket_bolt", formats)
        n = 6
        sk_r = sk / (2 * _m.cos(_m.pi / n))  # circumradius of hex socket
        ops = [
            {"op": "make_cylinder",  "id": "head", "R": hd/2, "H": hh},
            {"op": "make_cylinder",  "id": "body_raw", "R": d/2, "H": L},
            {"op": "translate",      "id": "body", "shape": "body_raw",
             "delta": [0, 0, -L]},
            {"op": "fuse",           "id": "bolt", "shapes": ["head", "body"]},
            # Socket: cuts from top face of head
            {"op": "make_reg_polygon", "id": "socket_raw",
             "n": n, "R": sk_r, "H": hh * 0.75},
            {"op": "translate", "id": "socket", "shape": "socket_raw",
             "delta": [0, 0, hh * 0.25]},
            {"op": "cut", "id": "bolt", "base": "bolt", "tools": ["socket"]},
        ]
        ops += self._export_ops("bolt", paths)
        ops.append({"op": "shape_info", "shape": "bolt"})
        return ops, paths

    def _build_knob(self, p: Dict, formats: List[str]):
        R     = float(p.get("R",  15))  # outer radius
        H     = float(p.get("H",  20))  # height
        bore  = float(p.get("bore", 6)) # bore radius
        n_cuts= int(p.get("n_cuts", 8)) # number of grip cuts
        cut_d = float(p.get("cut_d", 3)) # cut depth
        paths = self._make_output_paths("knob", formats)
        ops = [
            {"op": "make_cylinder", "id": "kn", "R": R, "H": H},
            {"op": "make_cylinder", "id": "bore_h", "R": bore, "H": H+2,
             "pos": [0, 0, -1]},
            {"op": "cut", "id": "kn", "base": "kn", "tools": ["bore_h"]},
        ]
        # Add grip cuts via polar array cut
        ops += [
            {"op": "make_box", "id": "cut1",
             "L": cut_d, "W": R*2, "H": H+2,
             "pos": [-cut_d/2, -R, -1]},
            {"op": "array_polar", "id": "cuts",
             "shape": "cut1", "count": n_cuts,
             "center": [0,0,0], "axis": [0,0,1], "total_angle": 360},
            {"op": "cut", "id": "kn", "base": "kn", "tools": ["cuts"]},
        ]
        ops += self._export_ops("kn", paths)
        ops.append({"op": "shape_info", "shape": "kn"})
        return ops, paths

    def _build_lug(self, p: Dict, formats: List[str]):
        W  = float(p.get("W",  20))   # lug width
        H  = float(p.get("H",  30))   # lug height
        T  = float(p.get("T",  6))    # thickness
        hole_d = float(p.get("hole_d", 8))  # hole diameter
        paths = self._make_output_paths("lug", formats)
        ops = [
            # Base rectangle
            {"op": "make_box", "id": "base", "L": W, "W": T, "H": H},
            # Round top (semicircle via cylinder cut)
            {"op": "make_cylinder", "id": "rnd", "R": W/2, "H": T+2,
             "pos": [W/2, -1, H - W/2]},
            {"op": "fuse", "id": "lug_body", "shapes": ["base", "rnd"]},
            # Mounting hole
            {"op": "make_cylinder", "id": "hole", "R": hole_d/2, "H": T+4,
             "pos": [W/2, -2, H - W/2]},
            {"op": "cut",   "id": "lug", "base": "lug_body", "tools": ["hole"]},
        ]
        ops += self._export_ops("lug", paths)
        ops.append({"op": "shape_info", "shape": "lug"})
        return ops, paths

    def _build_custom_ops(self, p: Dict, formats: List[str]):
        """Pass raw ops directly."""
        ops = p.get("ops", [])
        paths = p.get("paths", {})
        return ops, paths

    # ─────────────────────────────────────────────────────────────────────
    # Multi-step compound models
    # ─────────────────────────────────────────────────────────────────────

    def build_box_with_holes(self, L, W, H, hole_positions, hole_d=5.0, formats=None):
        """Box with drilled holes."""
        if formats is None:
            formats = ["stl", "step"]
        paths = self._make_output_paths("box_holes", formats)
        ops = [{"op": "make_box", "id": "base", "L": L, "W": W, "H": H}]
        for i, (hx, hy) in enumerate(hole_positions):
            ops.append({"op": "make_cylinder", "id": f"h{i}",
                        "R": hole_d / 2, "H": H + 2, "pos": [hx, hy, -1]})
        if hole_positions:
            ops.append({"op": "cut", "id": "result", "base": "base",
                        "tools": [f"h{i}" for i in range(len(hole_positions))]})
            final_id = "result"
        else:
            final_id = "base"
        ops += self._export_ops(final_id, paths)
        ops.append({"op": "shape_info", "shape": final_id})
        result = self.run_ops(ops, "box_with_holes")
        result["output_files"] = paths
        self._verify_outputs(result, paths)
        if paths.get("stl") and Path(paths["stl"]).exists():
            result["analysis"] = self.analyze_stl(paths["stl"])
        return result

    def build_pcb_standoffs(self, pcb_L, pcb_W, margin=3.5, od=6.0, id_=3.2, H=5.0,
                            formats=None):
        """4 PCB mounting standoffs at corners."""
        if formats is None:
            formats = ["stl"]
        positions = [
            [margin, margin],
            [pcb_L - margin, margin],
            [margin, pcb_W - margin],
            [pcb_L - margin, pcb_W - margin],
        ]
        paths = self._make_output_paths("pcb_standoffs", formats)
        ops = []
        for i, (x, y) in enumerate(positions):
            ops.append({"op": "make_tube", "id": f"so{i}",
                        "R_outer": od / 2, "R_inner": id_ / 2,
                        "H": H, "pos": [x - od / 2, y - od / 2, 0]})
        ops.append({"op": "compound", "id": "all_so",
                    "shapes": [f"so{i}" for i in range(4)]})
        ops += self._export_ops("all_so", paths)
        result = self.run_ops(ops, "pcb_standoffs")
        result["output_files"] = paths
        self._verify_outputs(result, paths)
        return result

    def build_bolt_pattern(self, n, pcd, bolt_d=8, bolt_L=30, formats=None):
        """N bolts on a pitch circle diameter."""
        if formats is None:
            formats = ["stl"]
        paths = self._make_output_paths(f"bolt_pattern_n{n}", formats)
        ops = []
        for i in range(n):
            angle = 2 * math.pi * i / n
            x = (pcd / 2) * math.cos(angle)
            y = (pcd / 2) * math.sin(angle)
            ops.append({"op": "make_hex_bolt", "id": f"bolt{i}",
                        "diameter": bolt_d, "length": bolt_L,
                        "head_h": bolt_d * 0.65, "head_w": bolt_d * 1.8})
            ops.append({"op": "translate", "id": f"bolt{i}_t",
                        "shape": f"bolt{i}", "delta": [x, y, 0]})
        ops.append({"op": "compound", "id": "bp",
                    "shapes": [f"bolt{i}_t" for i in range(n)]})
        ops += self._export_ops("bp", paths)
        result = self.run_ops(ops, "bolt_pattern")
        result["output_files"] = paths
        self._verify_outputs(result, paths)
        return result

    # ─────────────────────────────────────────────────────────────────────
    # Helper utilities
    # ─────────────────────────────────────────────────────────────────────

    def _verify_outputs(self, result: Dict, paths: Dict[str, str]) -> None:
        """Populate stl_ok/step_ok etc. based on file existence."""
        for fmt, path in paths.items():
            exists = Path(path).exists() and Path(path).stat().st_size > 100
            result[f"{fmt}_ok"] = exists
            if exists:
                result[f"{fmt}_path"] = path
                result[f"{fmt}_size"] = Path(path).stat().st_size
            else:
                result.setdefault("ok", False)
                result["ok"] = False

    def _export_ops(self, shape_id: str, paths: Dict[str, str]) -> List[Dict]:
        """Generate export operations for a given shape and set of paths."""
        ops = []
        for fmt, path in paths.items():
            op_name = f"export_{fmt}" if fmt in ("stl", "step", "brep", "obj") else f"export_{fmt}"
            ops.append({"op": op_name, "shape": shape_id, "path": path, "deflection": 0.05})
        return ops

    def check_environment(self) -> Dict:
        """Full environment check."""
        result = {
            "freecad_available": self.available(),
            "freecad_cmd": self.cmd,
            "backend_script": str(BACKEND_SCRIPT),
            "backend_exists": BACKEND_SCRIPT.exists(),
            "output_dir": str(self.output_dir),
        }
        # Check trimesh
        try:
            import trimesh
            result["trimesh"] = trimesh.__version__
        except ImportError:
            result["trimesh"] = None
        # Test FreeCAD subprocess
        if self.available():
            test_result = self.run_ops([
                {"op": "make_box", "id": "test_box", "L": 5, "W": 5, "H": 5},
                {"op": "shape_info", "shape": "test_box"},
            ], "env_check")
            result["freecad_test"] = test_result.get("ok", False)
            result["freecad_test_time"] = test_result.get("elapsed_s")
            result["freecad_errors"] = test_result.get("errors", [])
        return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli():
    parser = argparse.ArgumentParser(description="FreeCAD Model Builder CLI")
    sub = parser.add_subparsers(dest="cmd")

    # check
    sub.add_parser("check", help="Environment check")

    # build <type> [--params JSON] [--out dir]
    bp = sub.add_parser("build", help="Build a parametric model")
    bp.add_argument("type", help="Model type")
    bp.add_argument("--params", default="{}", help="JSON params")
    bp.add_argument("--out",    default=None,  help="Output directory")
    bp.add_argument("--formats", default="stl,step", help="Comma-separated export formats")

    # quick primitives
    for prim in ["box", "cylinder", "sphere", "enclosure", "hex_bolt", "gear_spur"]:
        pp = sub.add_parser(prim, help=f"Build {prim}")
        pp.add_argument("--params", default="{}", help="JSON params")
        pp.add_argument("--out",    default=None)
        pp.add_argument("--formats", default="stl,step")

    # ops <JSON_OPS_FILE>
    op_p = sub.add_parser("ops", help="Run raw ops from JSON file")
    op_p.add_argument("file", help="JSON file with ops list")

    # test
    sub.add_parser("test", help="Run quick smoke test")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        return

    builder = FCModelBuilder()

    if args.cmd == "check":
        info = builder.check_environment()
        print(json.dumps(info, indent=2))
        return

    if args.cmd == "test":
        from fc_test_suite import run_smoke_test
        run_smoke_test(builder)
        return

    if args.cmd == "ops":
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
        ops = data if isinstance(data, list) else data.get("ops", [])
        result = builder.run_ops(ops, "cli_ops")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # build / primitive shortcut
    model_type = getattr(args, "type", args.cmd)
    params = json.loads(args.params)
    out_dir = args.out
    formats = [f.strip() for f in args.formats.split(",")]
    result = builder.build(model_type, params, out_dir=out_dir, formats=formats)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _cli()
