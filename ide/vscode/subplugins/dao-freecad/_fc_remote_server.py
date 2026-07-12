#!/usr/bin/env python3
"""
道法自然 — FreeCAD GUI 远程控制服务器 v1.0

在 FreeCAD GUI 内部启动一个 HTTP 服务器，实现实时远程控制。
一切用户操作按钮功能，皆可通过 HTTP API 调用。
无为而无不为 — 用户于可感一切而无感一切操作。

API:
  GET  /status          — 实例状态
  GET  /commands         — 全部注册命令列表
  GET  /commands/<name>  — 单个命令详情
  GET  /workbenches      — 工作台列表
  GET  /document         — 当前文档状态
  GET  /documents        — 全部打开文档
  GET  /selection        — 当前选择
  GET  /screenshot       — 捕获3D视图截图 (PNG base64)
  GET  /scene            — 内核原生几何(三角网格+边线, 非像素): ?rev=上次版本&tol=容差
  POST /run_command      — 执行GUI命令 {"command": "Part_Box"}
  POST /exec             — 执行任意Python代码 {"code": "..."}
  POST /ops              — 执行backend ops序列
  POST /select           — 选择对象 {"doc": "...", "obj": "...", "sub": "..."}
  POST /view             — 视图操作 {"action": "fit_all|isometric|front|..."}
  POST /workbench        — 切换工作台 {"name": "PartWorkbench"}
  POST /property         — 读写属性 {"doc":"...", "obj":"...", "prop":"...", "value":...}
  POST /create_object    — 创建参数化对象 {"type":"Part::Box", "name":"MyBox", "props":{}}
  POST /export           — 导出 {"doc":"...", "format":"step", "path":"..."}
  POST /import_file      — 导入文件 {"path":"...", "format":"auto"}
  POST /sketch_pad       — Sketch→Pad {"geometry":[...], "length":10}
  POST /partdesign_body  — 完整参数化Body {"features":[...]}
  POST /assembly         — 多零件装配 {"pre_ops":[...], "parts":[...], "constraints":[...]}
  POST /techdraw         — 工程图生成 {"pre_ops":[...], "shape":"...", "output":"..."}
  POST /fem              — 有限元分析 {"pre_ops":[...], "shape":"...", "material":"steel"}

启动方式:
  1. freecad.exe _fc_remote_server.py
  2. 在FreeCAD Python控制台中:
     exec(open(r"E:\\道\\道生一\\一生二\\3D建模Agent\\_fc_remote_server.py").read())

默认端口: 18920
"""

import json
import sys
import os
import time
import threading
import traceback
import io
import base64
import queue
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ─── Configuration ────────────────────────────────────────────────────────────
PORT = int(os.environ.get("FC_REMOTE_PORT", "18920"))

# FC_REMOTE_TOOLS: 附加工具库目录(插件内置建模后端等), FreeCAD 内核对 PYTHONPATH
# 的处理因发行版而异, 故由本服务器显式注入 sys.path 保证 /exec 可 import
for _p in os.environ.get("FC_REMOTE_TOOLS", "").split(os.pathsep):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)
HOST = os.environ.get("FC_REMOTE_HOST", "127.0.0.1")
SCRIPT_DIR = Path(__file__).parent.resolve()

# ─── Thread-safe command queue for GUI-thread execution ───────────────────────
_cmd_queue = queue.Queue()
_result_map = {}
_result_lock = threading.Lock()
_cmd_counter = 0
_counter_lock = threading.Lock()


def _next_cmd_id():
    global _cmd_counter
    with _counter_lock:
        _cmd_counter += 1
        return _cmd_counter


def _exec_in_gui_thread(fn, timeout=30):
    """
    Schedule a function to run in FreeCAD's main/GUI thread via QTimer.
    Returns the result.
    """
    cmd_id = _next_cmd_id()
    event = threading.Event()

    _cmd_queue.put((cmd_id, fn, event))

    if event.wait(timeout=timeout):
        with _result_lock:
            return _result_map.pop(cmd_id, {"ok": False, "error": "no result"})
    else:
        return {"ok": False, "error": f"timeout after {timeout}s"}


def _gui_thread_worker():
    """
    Called periodically by QTimer in the main thread.
    Processes one command from the queue.
    """
    try:
        while not _cmd_queue.empty():
            cmd_id, fn, event = _cmd_queue.get_nowait()
            try:
                result = fn()
                if not isinstance(result, dict):
                    result = {"ok": True, "result": result}
            except Exception as e:
                result = {"ok": False, "error": str(e), "traceback": traceback.format_exc()}
            with _result_lock:
                _result_map[cmd_id] = result
            event.set()
    except queue.Empty:
        pass


# ─── API Handlers ─────────────────────────────────────────────────────────────

def _handle_status():
    """GET /status"""
    def _fn():
        import FreeCAD as App
        import FreeCADGui as Gui

        docs = list(App.listDocuments().keys())
        active_doc = App.ActiveDocument.Name if App.ActiveDocument else None
        active_wb = ""
        try:
            active_wb = Gui.activeWorkbench().name()
        except Exception:
            pass

        return {
            "ok": True,
            "freecad_version": App.Version(),
            "port": PORT,
            "documents": docs,
            "active_document": active_doc,
            "active_workbench": active_wb,
            "object_count": len(App.ActiveDocument.Objects) if App.ActiveDocument else 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    return _exec_in_gui_thread(_fn)


def _handle_commands():
    """GET /commands"""
    def _fn():
        import FreeCADGui as Gui
        try:
            from PySide2 import QtWidgets
        except ImportError:
            from PySide import QtWidgets

        commands = {}
        mw = Gui.getMainWindow()
        for act in mw.findChildren(QtWidgets.QAction):
            name = act.objectName()
            text = act.text().replace("&", "")
            if not name and not text:
                continue
            key = name or text
            commands[key] = {
                "text": text,
                "tooltip": (act.toolTip() or "")[:200],
                "shortcut": act.shortcut().toString() if act.shortcut() else "",
                "enabled": act.isEnabled(),
                "checkable": act.isCheckable(),
            }
        return {"ok": True, "commands": commands, "count": len(commands)}
    return _exec_in_gui_thread(_fn)


def _handle_workbenches():
    """GET /workbenches"""
    def _fn():
        import FreeCADGui as Gui
        wb_dict = Gui.listWorkbenches()
        active = ""
        try:
            active = Gui.activeWorkbench().name()
        except Exception:
            pass
        wbs = {}
        for name, cls in wb_dict.items():
            wbs[name] = {"class": str(cls)}
            try:
                wb = Gui.getWorkbench(name)
                if wb:
                    try:
                        wbs[name]["toolbars"] = list(wb.listToolbars())
                    except Exception:
                        pass
            except Exception:
                pass
        return {"ok": True, "workbenches": wbs, "active": active, "count": len(wbs)}
    return _exec_in_gui_thread(_fn)


def _handle_document():
    """GET /document"""
    def _fn():
        import FreeCAD as App
        doc = App.ActiveDocument
        if not doc:
            return {"ok": True, "document": None}
        objects = []
        for obj in doc.Objects:
            o = {
                "name": obj.Name, "label": obj.Label, "type": obj.TypeId,
                "properties": obj.PropertiesList[:80],
            }
            try:
                if hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                    o["volume"] = round(obj.Shape.Volume, 4)
                    o["faces"] = len(obj.Shape.Faces)
                    o["valid"] = obj.Shape.isValid()
            except Exception:
                pass
            objects.append(o)
        return {
            "ok": True,
            "document": {
                "name": doc.Name, "label": doc.Label, "file": doc.FileName,
                "objects": objects, "object_count": len(objects),
            }
        }
    return _exec_in_gui_thread(_fn)


def _handle_documents():
    """GET /documents"""
    def _fn():
        import FreeCAD as App
        docs = {}
        for name, doc in App.listDocuments().items():
            docs[name] = {
                "label": doc.Label, "file": doc.FileName,
                "object_count": len(doc.Objects),
                "modified": getattr(doc, 'Modified', None),
            }
        return {"ok": True, "documents": docs, "count": len(docs)}
    return _exec_in_gui_thread(_fn)


def _handle_selection():
    """GET /selection"""
    def _fn():
        import FreeCADGui as Gui
        sel = Gui.Selection.getSelectionEx()
        items = []
        for s in sel:
            item = {
                "object": s.ObjectName,
                "document": s.DocumentName,
                "sub_elements": [str(se) for se in s.SubElementNames],
            }
            try:
                item["type"] = s.Object.TypeId
            except Exception:
                pass
            items.append(item)
        return {"ok": True, "selection": items, "count": len(items)}
    return _exec_in_gui_thread(_fn)


def _handle_screenshot():
    """GET /screenshot"""
    def _fn():
        import FreeCADGui as Gui
        import tempfile
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if not view:
            return {"ok": False, "error": "no active view"}
        tmp = os.path.join(tempfile.gettempdir(), "_fc_screenshot.png")
        view.saveImage(tmp, 1920, 1080, "Current")
        if os.path.exists(tmp):
            with open(tmp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            os.remove(tmp)
            return {"ok": True, "format": "png", "width": 1920, "height": 1080,
                    "data": b64, "size": len(b64)}
        return {"ok": False, "error": "screenshot failed"}
    return _exec_in_gui_thread(_fn)


def _scene_revision():
    """Cheap monotonic-ish revision for the active document geometry."""
    import FreeCAD as App
    doc = App.ActiveDocument
    if not doc:
        return "none"
    parts = [doc.Name]
    for obj in doc.Objects:
        vis = True
        try:
            vis = bool(obj.ViewObject.Visibility)
        except Exception:
            pass
        h = ""
        try:
            if hasattr(obj, "Shape") and obj.Shape and not obj.Shape.isNull():
                h = str(obj.Shape.hashCode())
        except Exception:
            pass
        parts.append("%s:%s:%d" % (obj.Name, h, 1 if vis else 0))
    import hashlib
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:16]


def _handle_scene(query):
    """GET /scene — native kernel geometry (tessellated meshes + edges), no pixels.

    query: rev=<last revision>  → {"ok":true,"unchanged":true} if nothing moved
           tol=<tessellation tolerance mm> (default 0.1)
    """
    tol = 0.1
    try:
        tol = float(query.get("tol", ["0.1"])[0])
    except Exception:
        pass
    last = query.get("rev", [None])[0]

    def _fn():
        import FreeCAD as App
        rev = _scene_revision()
        if last and last == rev:
            return {"ok": True, "unchanged": True, "rev": rev}
        doc = App.ActiveDocument
        if not doc:
            return {"ok": True, "rev": rev, "document": None, "objects": []}
        sel = set()
        try:
            import FreeCADGui as Gui
            sel = {s.ObjectName for s in Gui.Selection.getSelectionEx()}
        except Exception:
            pass
        objects = []
        for obj in doc.Objects:
            vis = True
            color = [0.8, 0.8, 0.8]
            transparency = 0
            try:
                vo = obj.ViewObject
                vis = bool(vo.Visibility)
                if hasattr(vo, "ShapeColor"):
                    color = list(vo.ShapeColor)[:3]
                if hasattr(vo, "Transparency"):
                    transparency = int(vo.Transparency)
            except Exception:
                pass
            entry = {"name": obj.Name, "label": obj.Label, "type": obj.TypeId,
                     "visible": vis, "color": color, "transparency": transparency,
                     "selected": obj.Name in sel}
            try:
                shape = None
                if hasattr(obj, "Shape") and obj.Shape and not obj.Shape.isNull():
                    shape = obj.Shape
                if shape is not None and vis:
                    verts, faces = shape.tessellate(tol)
                    entry["vertices"] = [round(c, 4) for v in verts for c in (v.x, v.y, v.z)]
                    entry["faces"] = [i for f in faces for i in f]
                    edges = []
                    for e in shape.Edges:
                        try:
                            pts = e.discretize(Deflection=max(tol, 0.05))
                            edges.append([round(c, 4) for p in pts for c in (p.x, p.y, p.z)])
                        except Exception:
                            pass
                    entry["edges"] = edges
                elif hasattr(obj, "Mesh") and vis:
                    m = obj.Mesh
                    entry["vertices"] = [round(c, 4) for p in m.Points for c in (p.x, p.y, p.z)]
                    entry["faces"] = [i for f in m.Facets for i in f.PointIndices]
                    entry["edges"] = []
            except Exception as e:
                entry["mesh_error"] = str(e)
            objects.append(entry)
        return {"ok": True, "rev": rev,
                "document": {"name": doc.Name, "label": doc.Label, "file": doc.FileName},
                "objects": objects}
    return _exec_in_gui_thread(_fn, timeout=60)


def _handle_run_command(body):
    """POST /run_command"""
    cmd_name = body.get("command", "")
    if not cmd_name:
        return {"ok": False, "error": "command required"}

    def _fn():
        import FreeCADGui as Gui
        Gui.runCommand(cmd_name)
        return {"ok": True, "command": cmd_name, "executed": True}
    return _exec_in_gui_thread(_fn)


def _handle_exec(body):
    """POST /exec"""
    code = body.get("code", "")
    if not code:
        return {"ok": False, "error": "code required"}

    def _fn():
        import FreeCAD as App
        import FreeCADGui as Gui
        import Part
        from FreeCAD import Base

        local_ns = {
            "App": App, "Gui": Gui, "Part": Part, "Base": Base,
            "FreeCAD": App, "FreeCADGui": Gui,
            "__result__": None,
        }
        exec(code, local_ns)
        result_val = local_ns.get("__result__")
        if result_val is not None:
            return {"ok": True, "result": str(result_val)[:10000]}
        return {"ok": True, "executed": True}
    return _exec_in_gui_thread(_fn)


def _handle_ops(body):
    """POST /ops"""
    ops = body.get("ops", [])
    if not ops:
        return {"ok": False, "error": "ops required"}

    def _fn():
        # Import backend
        sys.path.insert(0, str(SCRIPT_DIR))
        from freecad_backend import run_ops
        result = run_ops(ops)
        return result
    return _exec_in_gui_thread(_fn, timeout=120)


def _handle_select(body):
    """POST /select"""
    def _fn():
        import FreeCAD as App
        import FreeCADGui as Gui

        action = body.get("action", "add")  # add / remove / clear / toggle
        doc_name = body.get("doc", "")
        obj_name = body.get("obj", "")
        sub = body.get("sub", "")

        if action == "clear":
            Gui.Selection.clearSelection()
            return {"ok": True, "action": "clear"}

        doc = App.getDocument(doc_name) if doc_name else App.ActiveDocument
        if not doc:
            return {"ok": False, "error": "no document"}

        if action == "add":
            Gui.Selection.addSelection(doc.Name, obj_name, sub)
        elif action == "remove":
            Gui.Selection.removeSelection(doc.Name, obj_name, sub)
        elif action == "toggle":
            # Check if selected, then toggle
            sel = Gui.Selection.getSelection(doc.Name)
            names = [s.Name for s in sel]
            if obj_name in names:
                Gui.Selection.removeSelection(doc.Name, obj_name)
            else:
                Gui.Selection.addSelection(doc.Name, obj_name, sub)

        return {"ok": True, "action": action, "obj": obj_name}
    return _exec_in_gui_thread(_fn)


def _handle_view(body):
    """POST /view"""
    action = body.get("action", "fit_all")

    def _fn():
        import FreeCAD as App
        import FreeCADGui as Gui
        if not Gui.ActiveDocument:
            # GUI 运行时 App.newDocument 会自动创建 Gui.Document
            # (FreeCAD 1.0 中无 Gui.showDocument 方法)
            doc = App.newDocument("Default")
            doc.recompute()
            try:
                Gui.updateGui()
            except Exception:
                pass
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if not view:
            return {"ok": False, "error": "no active view"}

        VIEW_ACTIONS = {
            "fit_all": "fitAll",
            "isometric": "viewIsometric",
            "front": "viewFront",
            "rear": "viewRear",
            "top": "viewTop",
            "bottom": "viewBottom",
            "left": "viewLeft",
            "right": "viewRight",
            "home": "viewHome",
            "axonometric": "viewAxonometric",
        }

        if action == "zoom_in":
            view.zoomIn()
            return {"ok": True, "action": action}
        if action == "zoom_out":
            view.zoomOut()
            return {"ok": True, "action": action}

        fn_name = VIEW_ACTIONS.get(action)
        if fn_name:
            getattr(view, fn_name)()
            return {"ok": True, "action": action}

        if action == "set_camera":
            # {"action": "set_camera", "position": [x,y,z], "direction": [x,y,z]}
            pos = body.get("position")
            dirn = body.get("direction")
            if dirn:
                from FreeCAD import Base
                d = Base.Vector(*dirn)
                if d.Length < 1e-9:
                    return {"ok": False, "error": "zero direction"}
                d.normalize()
                view.setCameraOrientation(Base.Rotation(Base.Vector(0, 0, -1), d))
                return {"ok": True, "action": "set_camera"}

        if action == "perspective":
            view.setCameraType("Perspective")
            return {"ok": True, "action": "perspective"}
        elif action == "orthographic":
            view.setCameraType("Orthographic")
            return {"ok": True, "action": "orthographic"}

        return {"ok": False, "error": f"unknown view action: {action}"}
    return _exec_in_gui_thread(_fn)


def _handle_workbench(body):
    """POST /workbench"""
    name = body.get("name", "")
    if not name:
        return {"ok": False, "error": "workbench name required"}

    def _fn():
        import FreeCADGui as Gui
        Gui.activateWorkbench(name)
        return {"ok": True, "workbench": name}
    return _exec_in_gui_thread(_fn)


def _handle_property(body):
    """POST /property"""
    def _fn():
        import FreeCAD as App

        doc_name = body.get("doc", "")
        obj_name = body.get("obj", "")
        prop_name = body.get("prop", "")
        value = body.get("value", None)

        doc = App.getDocument(doc_name) if doc_name else App.ActiveDocument
        if not doc:
            return {"ok": False, "error": "no document"}
        obj = doc.getObject(obj_name)
        if not obj:
            return {"ok": False, "error": f"object '{obj_name}' not found"}
        if not prop_name:
            # Return all properties
            props = {}
            for p in obj.PropertiesList:
                try:
                    props[p] = repr(getattr(obj, p))[:200]
                except Exception:
                    props[p] = "<error>"
            return {"ok": True, "properties": props}

        if value is not None:
            # Write property
            setattr(obj, prop_name, value)
            doc.recompute()
            return {"ok": True, "set": prop_name, "value": repr(value)[:200]}
        else:
            # Read property
            val = getattr(obj, prop_name)
            return {"ok": True, "prop": prop_name, "value": repr(val)[:500]}
    return _exec_in_gui_thread(_fn)


def _handle_create_object(body):
    """POST /create_object"""
    def _fn():
        import FreeCAD as App

        type_id = body.get("type", "Part::Box")
        name = body.get("name", "Object")
        props = body.get("props", {})
        doc_name = body.get("doc", "")

        doc = App.getDocument(doc_name) if doc_name else App.ActiveDocument
        if not doc:
            doc = App.newDocument("Unnamed")

        obj = doc.addObject(type_id, name)
        for k, v in props.items():
            try:
                setattr(obj, k, v)
            except Exception:
                pass
        doc.recompute()

        return {
            "ok": True, "object": obj.Name, "type": type_id,
            "document": doc.Name,
        }
    return _exec_in_gui_thread(_fn)


def _handle_export(body):
    """POST /export"""
    def _fn():
        import FreeCAD as App
        import Part

        doc_name = body.get("doc", "")
        obj_names = body.get("objects", [])
        path = body.get("path", "")
        fmt = body.get("format", "step")

        doc = App.getDocument(doc_name) if doc_name else App.ActiveDocument
        if not doc:
            return {"ok": False, "error": "no document"}
        if not path:
            return {"ok": False, "error": "path required"}

        # Collect both objects (for Mesh.export) and shapes (for Part.export)
        export_objs = []
        shapes = []
        for obj_name in (obj_names or [o.Name for o in doc.Objects]):
            obj = doc.getObject(obj_name)
            if obj and hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                export_objs.append(obj)
                shapes.append(obj.Shape)

        if not shapes:
            return {"ok": False, "error": "no shapes to export"}

        compound = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if fmt.lower() in ("step", "stp"):
            Part.export(shapes, path)
        elif fmt.lower() == "stl":
            import Mesh
            try:
                # Best method: Mesh.export with document objects
                Mesh.export(export_objs, path)
            except Exception:
                try:
                    # Fallback: MeshPart.meshFromShape
                    import MeshPart
                    combined = MeshPart.meshFromShape(Shape=compound,
                                                      LinearDeflection=0.1,
                                                      AngularDeflection=0.5)
                    combined.write(path)
                except Exception as e2:
                    return {"ok": False, "error": f"STL export failed: {e2}"}
        elif fmt.lower() in ("brep", "brp"):
            compound.exportBrep(path)
        elif fmt.lower() in ("iges", "igs"):
            Part.export(shapes, path)
        elif fmt.lower() == "fcstd":
            doc.saveAs(path)
        else:
            return {"ok": False, "error": f"unsupported format: {fmt}"}

        size = os.path.getsize(path) if os.path.exists(path) else 0
        return {"ok": True, "path": path, "format": fmt, "size": size}
    return _exec_in_gui_thread(_fn)


def _handle_sketch_pad(body):
    """POST /sketch_pad  — Convenience: Sketch → Pad in one call"""
    geometry = body.get("geometry", [])
    if not geometry:
        return {"ok": False, "error": "geometry required"}
    ops = [{"op": "sketch_pad", "id": "result",
            "geometry": geometry,
            "length": body.get("length", 10),
            "plane": body.get("plane", "XY"),
            "constraints": body.get("constraints", []),
            "symmetric": body.get("symmetric", False),
            "taper": body.get("taper", 0)}]
    if body.get("export_stl"):
        ops.append({"op": "export_stl", "shape": "result",
                     "path": body["export_stl"]})
    if body.get("export_step"):
        ops.append({"op": "export_step", "shape": "result",
                     "path": body["export_step"]})
    return _handle_ops({"ops": ops})


def _handle_partdesign_body(body):
    """POST /partdesign_body  — Full parametric body with feature tree"""
    features = body.get("features", [])
    if not features:
        return {"ok": False, "error": "features list required"}
    ops = [{"op": "partdesign_body", "id": "result", "features": features}]
    if body.get("export_stl"):
        ops.append({"op": "export_stl", "shape": "result",
                     "path": body["export_stl"]})
    if body.get("export_step"):
        ops.append({"op": "export_step", "shape": "result",
                     "path": body["export_step"]})
    if body.get("techdraw"):
        td = body["techdraw"]
        ops.append({"op": "techdraw", "shape": "result",
                     "output": td.get("output", "drawing.svg"),
                     "title": td.get("title", "Drawing")})
    return _handle_ops({"ops": ops})


def _handle_assembly(body):
    """POST /assembly  — Multi-part assembly with constraints"""
    # Pre-ops to create parts
    pre_ops = body.get("pre_ops", [])
    parts = body.get("parts", [])
    constraints = body.get("constraints", [])
    if not parts:
        return {"ok": False, "error": "parts list required"}
    ops = list(pre_ops)
    ops.append({"op": "assembly", "id": "asm",
                "parts": parts, "constraints": constraints,
                "save_path": body.get("save_path")})
    if body.get("export_step"):
        ops.append({"op": "export_step", "shape": "asm",
                     "path": body["export_step"]})
    return _handle_ops({"ops": ops})


def _handle_techdraw(body):
    """POST /techdraw  — Generate technical drawing SVG"""
    pre_ops = body.get("pre_ops", [])
    shape_id = body.get("shape", "")
    output = body.get("output", "")
    if not shape_id or not output:
        return {"ok": False, "error": "shape and output required"}
    ops = list(pre_ops)
    ops.append({"op": "techdraw", "id": "td", "shape": shape_id,
                "output": output,
                "views": body.get("views"),
                "title": body.get("title", "Technical Drawing"),
                "scale": body.get("scale", 1.0)})
    return _handle_ops({"ops": ops})


def _handle_fem(body):
    """POST /fem  — FEM analysis (mesh + stress estimate)"""
    pre_ops = body.get("pre_ops", [])
    shape_id = body.get("shape", "")
    if not shape_id:
        return {"ok": False, "error": "shape id required"}
    ops = list(pre_ops)
    if body.get("mesh", True):
        mesh_op = {"op": "fem_mesh", "id": "mesh", "shape": shape_id,
                   "deflection": body.get("deflection", 0.1)}
        if body.get("mesh_path"):
            mesh_op["path"] = body["mesh_path"]
        ops.append(mesh_op)
    if body.get("stress", False):
        ops.append({"op": "fem_stress_estimate", "id": "stress",
                     "shape": shape_id,
                     "force_N": body.get("force_N", 100),
                     "material": body.get("material", "steel")})
    return _handle_ops({"ops": ops})


def _handle_import_file(body):
    """POST /import_file"""
    def _fn():
        import FreeCAD as App

        path = body.get("path", "")
        if not path or not os.path.exists(path):
            return {"ok": False, "error": f"file not found: {path}"}

        ext = Path(path).suffix.lower()
        if ext == ".fcstd":
            doc = App.openDocument(path)
            return {"ok": True, "document": doc.Name, "objects": len(doc.Objects)}
        elif ext in (".step", ".stp", ".iges", ".igs", ".brep", ".brp"):
            import Part
            shape = Part.read(path)
            doc = App.ActiveDocument or App.newDocument("Imported")
            obj = doc.addObject("Part::Feature", Path(path).stem)
            obj.Shape = shape
            doc.recompute()
            return {"ok": True, "object": obj.Name, "document": doc.Name}
        elif ext in (".stl", ".obj", ".ply", ".off"):
            import Mesh
            doc = App.ActiveDocument or App.newDocument("Imported")
            Mesh.insert(path, doc.Name)
            doc.recompute()
            return {"ok": True, "document": doc.Name}
        else:
            # Try generic import
            App.openDocument(path)
            return {"ok": True}
    return _exec_in_gui_thread(_fn)


# ─── 整窗路由: 全部 FreeCAD UI → 网页 ────────────────────────────────────────

def _keycode(QtGui, s):
    try:
        k = QtGui.QKeySequence(s)[0]
        return k.toCombined() if hasattr(k, "toCombined") else int(k)
    except Exception:
        return 0


def _qt():
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


def _handle_window(query):
    """GET /window — 整个 FreeCAD 主窗口(含菜单/对话框等弹层)帧捕获."""
    scale = float(query.get("scale", ["1"])[0])
    fmt = query.get("fmt", ["jpg"])[0].lower()
    quality = int(query.get("q", ["70"])[0])

    def _fn():
        import FreeCADGui as Gui
        QtCore, QtGui, QtWidgets = _qt()
        mw = Gui.getMainWindow()
        pix = mw.grab()
        origin = mw.mapToGlobal(QtCore.QPoint(0, 0))
        painter = QtGui.QPainter(pix)
        for w in QtWidgets.QApplication.topLevelWidgets():
            if w is mw or not w.isVisible() or w.width() <= 1:
                continue
            off = w.mapToGlobal(QtCore.QPoint(0, 0)) - origin
            painter.drawPixmap(off, w.grab())
        painter.end()
        w0, h0 = pix.width(), pix.height()
        if scale != 1:
            pix = pix.scaledToWidth(int(w0 * scale), QtCore.Qt.SmoothTransformation)
        buf = QtCore.QBuffer()
        buf.open(QtCore.QBuffer.WriteOnly)
        if fmt == "png":
            pix.save(buf, "PNG")
        else:
            pix.save(buf, "JPG", quality)
        data = bytes(buf.data())
        buf.close()
        return {"ok": True, "format": fmt, "window_width": w0, "window_height": h0,
                "width": pix.width(), "height": pix.height(),
                "data": base64.b64encode(data).decode("ascii")}
    return _exec_in_gui_thread(_fn)


_MOUSE_BUTTONS_DOWN = set()
# 网页路由时 FreeCAD 窗口非 OS 活动窗口, Qt 不会自动赋予键盘焦点;
# 故记录最近一次鼠标按下命中的控件, 作为键盘事件的显式目标.
_LAST_CLICK_TARGET = [None]


def _handle_input(body):
    """POST /input — 鼠键事件回注入 FreeCAD Qt 本体(坐标为主窗口内坐标).

    {"type":"mouse_move|mouse_down|mouse_up|dblclick|wheel|key_down|key_up|text",
     "x":..,"y":..,"button":"left|right|middle","delta":120,"key":"Return",
     "text":"abc","modifiers":["ctrl","shift","alt"]}
    """
    def _fn():
        import FreeCADGui as Gui
        QtCore, QtGui, QtWidgets = _qt()
        Qt = QtCore.Qt
        mw = Gui.getMainWindow()
        etype = body.get("type", "")
        mods = Qt.KeyboardModifiers()
        for m in body.get("modifiers", []):
            mods |= {"ctrl": Qt.ControlModifier, "shift": Qt.ShiftModifier,
                     "alt": Qt.AltModifier, "meta": Qt.MetaModifier}.get(m, Qt.NoModifier)

        if etype in ("mouse_move", "mouse_down", "mouse_up", "dblclick", "wheel"):
            x, y = int(body.get("x", 0)), int(body.get("y", 0))
            gp = mw.mapToGlobal(QtCore.QPoint(x, y))
            container = QtWidgets.QApplication.activePopupWidget()
            if container is None:
                for tlw in QtWidgets.QApplication.topLevelWidgets():
                    if (tlw is not mw and tlw.isVisible() and tlw.isWindow()
                            and tlw.geometry().contains(gp)):
                        container = tlw
                        break
            if container is None:
                container = mw
            child = container.childAt(container.mapFromGlobal(gp))
            target = child or container
            lp = target.mapFromGlobal(gp)
            btn_name = body.get("button", "left")
            btn = {"left": Qt.LeftButton, "right": Qt.RightButton,
                   "middle": Qt.MiddleButton}.get(btn_name, Qt.LeftButton)

            # QGraphicsView(Quarter 3D 视口)鼠标/滚轮事件须收在视图本体而非 viewport
            parent = target.parentWidget()
            if isinstance(parent, QtWidgets.QGraphicsView) and target is parent.viewport():
                target = parent
                lp = target.mapFromGlobal(gp)

            if etype == "wheel":
                delta = int(body.get("delta", 120))
                ev = QtGui.QWheelEvent(
                    QtCore.QPointF(lp), QtCore.QPointF(gp),
                    QtCore.QPoint(0, 0), QtCore.QPoint(0, delta),
                    Qt.NoButton, mods, Qt.NoScrollPhase, False)
                QtWidgets.QApplication.postEvent(target, ev)
                return {"ok": True, "type": etype, "target": target.__class__.__name__}

            if etype == "mouse_down":
                _MOUSE_BUTTONS_DOWN.add(btn_name)
                qev, evbtn = QtCore.QEvent.MouseButtonPress, btn
                # 合成点击不触发焦点转移(真实点击由 Qt 自动处理), 此处补齐键盘焦点
                w = target
                while w is not None and w.focusPolicy() == Qt.NoFocus:
                    w = w.parentWidget()
                if w is not None and w.focusPolicy() & Qt.ClickFocus:
                    w.setFocus(Qt.MouseFocusReason)
                    _LAST_CLICK_TARGET[0] = w
                else:
                    _LAST_CLICK_TARGET[0] = target
            elif etype == "mouse_up":
                _MOUSE_BUTTONS_DOWN.discard(btn_name)
                qev, evbtn = QtCore.QEvent.MouseButtonRelease, btn
            elif etype == "dblclick":
                qev, evbtn = QtCore.QEvent.MouseButtonDblClick, btn
            else:
                qev, evbtn = QtCore.QEvent.MouseMove, Qt.NoButton

            buttons = Qt.MouseButtons()
            for b in _MOUSE_BUTTONS_DOWN:
                buttons |= {"left": Qt.LeftButton, "right": Qt.RightButton,
                            "middle": Qt.MiddleButton}[b]
            ev = QtGui.QMouseEvent(qev, QtCore.QPointF(lp), QtCore.QPointF(gp),
                                   evbtn, buttons, mods)
            QtWidgets.QApplication.postEvent(target, ev)
            return {"ok": True, "type": etype, "target": target.__class__.__name__}

        if etype in ("key_down", "key_up", "text"):
            last = _LAST_CLICK_TARGET[0]
            if last is not None:
                try:
                    if not last.isVisible():
                        last = None
                except RuntimeError:  # 已销毁
                    last = _LAST_CLICK_TARGET[0] = None
            target = (QtWidgets.QApplication.activePopupWidget()
                      or QtWidgets.QApplication.focusWidget()
                      or mw.focusWidget() or last or mw)
            if etype == "text":
                for ch in body.get("text", ""):
                    key = _keycode(QtGui, ch) if ch.strip() else Qt.Key_Space
                    QtWidgets.QApplication.postEvent(
                        target, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, key, mods, ch))
                    QtWidgets.QApplication.postEvent(
                        target, QtGui.QKeyEvent(QtCore.QEvent.KeyRelease, key, mods, ch))
                return {"ok": True, "type": "text"}
            name = body.get("key", "")
            special = {"Return": Qt.Key_Return, "Enter": Qt.Key_Enter, "Tab": Qt.Key_Tab,
                       "Escape": Qt.Key_Escape, "Backspace": Qt.Key_Backspace,
                       "Delete": Qt.Key_Delete, "Up": Qt.Key_Up, "Down": Qt.Key_Down,
                       "Left": Qt.Key_Left, "Right": Qt.Key_Right, "Home": Qt.Key_Home,
                       "End": Qt.Key_End, "PageUp": Qt.Key_PageUp, "PageDown": Qt.Key_PageDown,
                       "Space": Qt.Key_Space, "F1": Qt.Key_F1}
            key = special.get(name) or _keycode(QtGui, name)
            text = name if len(name) == 1 else ""
            qev = QtCore.QEvent.KeyPress if etype == "key_down" else QtCore.QEvent.KeyRelease
            # postEvent 直达控件会绕过 QShortcutMap(Del/Ctrl+Z 等动作快捷键),
            # 且窗口非活动时快捷键不匹配 —— 显式按快捷键触发对应 QAction
            if etype == "key_down" and target is not None and not QtWidgets.QApplication.activePopupWidget():
                fw = QtWidgets.QApplication.focusWidget()
                editing = isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QTextEdit,
                                          QtWidgets.QPlainTextEdit, QtWidgets.QAbstractSpinBox))
                seq = QtGui.QKeySequence(int(mods.value if hasattr(mods, "value") else int(mods)) | int(key))
                if not (editing and len(name) == 1):
                    for act in mw.findChildren(QtGui.QAction):
                        if act.isEnabled() and not act.shortcut().isEmpty() \
                                and act.shortcut().matches(seq) == QtGui.QKeySequence.ExactMatch:
                            act.trigger()
                            return {"ok": True, "type": "shortcut", "action": act.objectName() or act.text()}
            QtWidgets.QApplication.postEvent(
                target, QtGui.QKeyEvent(qev, key, mods, text))
            return {"ok": True, "type": etype, "key": name}

        return {"ok": False, "error": "unknown input type: %s" % etype}
    return _exec_in_gui_thread(_fn)


# ─── DAO 智体桥: 235+ 工具面 + AI 对话 ───────────────────────────────────────

_dao_engine = None


def _dao_root():
    """定位 DAO 模块根: 仓库布局(<repo>/freecad/DAO) 或插件内置(<plugin>/dao/freecad/DAO)."""
    for root in (SCRIPT_DIR.parent, SCRIPT_DIR / "dao"):
        if (root / "freecad" / "DAO").is_dir():
            return root
    return SCRIPT_DIR.parent


def _get_engine():
    global _dao_engine
    if _dao_engine is None:
        dao_dir = str(_dao_root() / "freecad" / "DAO")
        if dao_dir not in sys.path:
            sys.path.insert(0, dao_dir)
        import dao_engine
        _dao_engine = dao_engine.DAOEngine()
    return _dao_engine


def _handle_tools():
    """GET /tools — DAO 全工具面(solid./param./asm./gui./doc. …)."""
    def _fn():
        eng = _get_engine()
        return {"ok": True, "ops": eng.ops(), "count": len(eng.ops())}
    return _exec_in_gui_thread(_fn, timeout=60)


def _handle_toolspec():
    """GET /toolspec — Devin-Desktop 式工具目录: 每个 op 的描述 + 参数契约 + 分组."""
    def _fn():
        eng = _get_engine()
        repo = str(_dao_root())
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from cad_agent import tool_catalog
        cat = tool_catalog.build_catalog(eng.ops())
        cat["ok"] = True
        return cat
    return _exec_in_gui_thread(_fn, timeout=60)


def _handle_tool(body):
    """POST /tool — 直接调用单个 DAO 工具 {"op":"solid.box","args":{...}}."""
    op = body.get("op", "")
    args = body.get("args", {})
    if not op:
        return {"ok": False, "error": "op required"}

    def _fn():
        eng = _get_engine()
        eng._ensure_doc()
        fn = eng.handlers.get(op)
        if fn is None:
            return {"ok": False, "error": "unknown op: %s" % op}
        data = fn(args)
        if not isinstance(data, dict):
            data = {"value": data}
        return {"ok": True, "op": op, "data": data}
    return _exec_in_gui_thread(_fn, timeout=120)


def _handle_agent(body):
    """POST /agent — AI 对话式建模 {"text":"造一个 80x80x120 的盒子"}."""
    text = body.get("text", "")
    if not text:
        return {"ok": False, "error": "text required"}

    def _fn():
        eng = _get_engine()
        note, results = eng.run(text)
        return {"ok": True, "note": note, "results": results}
    return _exec_in_gui_thread(_fn, timeout=300)


def _dao_modules():
    """Import the DAO AI-IDE modules (llm/prompts/sessions) lazily."""
    dao_dir = str(_dao_root() / "freecad" / "DAO")
    if dao_dir not in sys.path:
        sys.path.insert(0, dao_dir)
    import dao_llm
    import dao_prompts
    import dao_sessions
    return dao_llm, dao_prompts, dao_sessions


def _handle_aiconfig_get():
    """GET /aiconfig — AI 供应商配置(密钥打码)."""
    dao_llm, _, _ = _dao_modules()
    cfg = dao_llm.load_config()
    key = cfg.get("api_key") or ""
    cfg["api_key"] = (key[:6] + "…") if key else ""
    cfg["configured"] = dao_llm.configured()
    cfg.pop("api_token", None)
    return {"ok": True, "config": cfg}


def _handle_aiconfig_post(body):
    """POST /aiconfig — 更新 base_url/api_key/model/temperature/max_steps."""
    dao_llm, _, _ = _dao_modules()
    cfg = dao_llm.load_config()
    for k in ("base_url", "api_key", "model", "temperature",
              "max_steps", "system_prompt_id"):
        if body.get(k) not in (None, ""):
            cfg[k] = body[k]
    dao_llm.save_config(cfg)
    return {"ok": True, "configured": dao_llm.configured(cfg)}


def _handle_chat(body):
    """POST /chat — 真·LLM 对话式建模(工具调用闭环, 仿 Devin Desktop).

    {"text": "...", "session": "<id 可选>"} — 会话历史自动持久化续聊；
    无模型配置时报错并指引 /aiconfig。"""
    text = body.get("text", "")
    if not text:
        return {"ok": False, "error": "text required"}
    dao_llm, dao_prompts, dao_sessions = _dao_modules()
    if not dao_llm.configured():
        return {"ok": False, "error": "AI 未配置：先 POST /aiconfig "
                "{base_url, api_key, model}（任意 OpenAI 兼容端点）",
                "need_config": True}

    def _fn():
        eng = _get_engine()
        eng._ensure_doc()

        def actor(tool, args):
            fn = eng.handlers.get(tool)
            if fn is None:
                raise KeyError("unknown tool: %s" % tool)
            return fn(args or {})

        cfg = dao_llm.load_config()
        agent = dao_llm.LLMAgent(
            actor, cfg=cfg,
            system_prompt=dao_prompts.system_prompt(
                cfg.get("system_prompt_id", "default"), eng.ops()))
        sid = body.get("session")
        conv = (dao_sessions.load(sid) if sid else None) or \
            dao_sessions.create(title=text[:40])
        sid = conv["id"]
        out = agent.ask(text, history=conv.get("messages") or [])
        dao_sessions.save_messages(sid, out["messages"])
        return {"ok": True, "session": sid, "say": out["say"],
                "actions": out["actions"], "verify": out.get("verify")}
    return _exec_in_gui_thread(_fn, timeout=600)


def _handle_sessions():
    """GET /sessions — 会话列表(仿 Devin Desktop 会话管理)."""
    _, _, dao_sessions = _dao_modules()
    return {"ok": True, "sessions": dao_sessions.list_all()}


# ─── HTTP Request Handler ────────────────────────────────────────────────────

class FreeCADRemoteHandler(BaseHTTPRequestHandler):
    """HTTP handler for FreeCAD remote control"""

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ui_response(self, path):
        """GET /ui \u2014 serve the unified single-page IDE frontend."""
        rel = path[len("/ui"):].lstrip("/") or "index.html"
        root = os.environ.get("FC_REMOTE_UI") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "90-\u5f52\u4e00_IDE", "web")
        f = os.path.abspath(os.path.join(root, rel))
        if not f.startswith(os.path.abspath(root)) or not os.path.isfile(f):
            self._json_response({"ok": False, "error": "ui asset not found", "path": f}, 404)
            return
        ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                 ".png": "image/png", ".svg": "image/svg+xml"}.get(os.path.splitext(f)[1], "application/octet-stream")
        with open(f, "rb") as fp:
            body = fp.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        try:
            if path == "" or path == "/status":
                self._json_response(_handle_status())
            elif path == "/commands":
                self._json_response(_handle_commands())
            elif path == "/workbenches":
                self._json_response(_handle_workbenches())
            elif path == "/document":
                self._json_response(_handle_document())
            elif path == "/documents":
                self._json_response(_handle_documents())
            elif path == "/selection":
                self._json_response(_handle_selection())
            elif path == "/screenshot":
                self._json_response(_handle_screenshot())
            elif path == "/scene":
                self._json_response(_handle_scene(parse_qs(parsed.query)))
            elif path == "/window":
                self._json_response(_handle_window(parse_qs(parsed.query)))
            elif path == "/tools":
                self._json_response(_handle_tools())
            elif path == "/toolspec":
                self._json_response(_handle_toolspec())
            elif path == "/aiconfig":
                self._json_response(_handle_aiconfig_get())
            elif path == "/sessions":
                self._json_response(_handle_sessions())
            elif path == "/ui" or path.startswith("/ui/"):
                self._ui_response(path)
            else:
                self._json_response({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json_response({"ok": False, "error": str(e)}, 500)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json_response({"ok": False, "error": "invalid JSON"}, 400)
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        try:
            if path == "/run_command":
                self._json_response(_handle_run_command(body))
            elif path == "/exec":
                self._json_response(_handle_exec(body))
            elif path == "/ops":
                self._json_response(_handle_ops(body))
            elif path == "/select":
                self._json_response(_handle_select(body))
            elif path == "/view":
                self._json_response(_handle_view(body))
            elif path == "/workbench":
                self._json_response(_handle_workbench(body))
            elif path == "/property":
                self._json_response(_handle_property(body))
            elif path == "/create_object":
                self._json_response(_handle_create_object(body))
            elif path == "/export":
                self._json_response(_handle_export(body))
            elif path == "/import_file":
                self._json_response(_handle_import_file(body))
            elif path == "/sketch_pad":
                self._json_response(_handle_sketch_pad(body))
            elif path == "/partdesign_body":
                self._json_response(_handle_partdesign_body(body))
            elif path == "/assembly":
                self._json_response(_handle_assembly(body))
            elif path == "/techdraw":
                self._json_response(_handle_techdraw(body))
            elif path == "/fem":
                self._json_response(_handle_fem(body))
            elif path == "/input":
                self._json_response(_handle_input(body))
            elif path == "/tool":
                self._json_response(_handle_tool(body))
            elif path == "/agent":
                self._json_response(_handle_agent(body))
            elif path == "/chat":
                self._json_response(_handle_chat(body))
            elif path == "/aiconfig":
                self._json_response(_handle_aiconfig_post(body))
            else:
                self._json_response({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json_response({"ok": False, "error": str(e)}, 500)


# ─── Server Lifecycle ─────────────────────────────────────────────────────────

if "_server" not in globals():
    _server = None
    _timer = None


def start_server(port=None, host=None):
    """
    启动远程控制服务器

    在FreeCAD Python控制台中一行启动:
        exec(open(r"path/to/_fc_remote_server.py").read())
    """
    global _server, _timer, PORT, HOST

    if port:
        PORT = port
    if host:
        HOST = host

    # Start HTTP server in daemon thread
    _server = HTTPServer((HOST, PORT), FreeCADRemoteHandler)
    _server.timeout = 0.5

    def _serve():
        while _server:
            try:
                _server.handle_request()
            except Exception:
                break

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    # Start QTimer for GUI-thread command processing
    try:
        try:
            from PySide2 import QtCore
        except ImportError:
            from PySide import QtCore
        _timer = QtCore.QTimer()
        _timer.timeout.connect(_gui_thread_worker)
        _timer.start(50)  # 50ms polling interval
    except Exception as e:
        print(f"[RemoteServer] WARNING: QTimer failed: {e}")
        print("[RemoteServer] GUI-thread commands will not work properly.")

    print(f"")
    print(f"  {'='*56}")
    print(f"  FreeCAD Remote Control Server v1.0")
    print(f"  {'='*56}")
    print(f"  Status:    http://{HOST}:{PORT}/status")
    print(f"  Commands:  http://{HOST}:{PORT}/commands")
    print(f"  Document:  http://{HOST}:{PORT}/document")
    print(f"  Screenshot:http://{HOST}:{PORT}/screenshot")
    print(f"  {'='*56}")
    print(f"  POST /run_command  {'{'}\"command\": \"Part_Box\"{'}'}")
    print(f"  POST /exec         {'{'}\"code\": \"print(1+1)\"{'}'}")
    print(f"  POST /view         {'{'}\"action\": \"isometric\"{'}'}")
    print(f"  {'='*56}")
    print(f"")

    # 后台桥接形态：最小化主窗，不抢用户/IDE 焦点（FC_REMOTE_MINIMIZE=0 关闭）。
    # 主窗可能在本函数之后才完成渲染，首启对话框(OpenGL/欢迎页)也可能把窗口还原，
    # 故除立即最小化外，再经 QTimer 延时补打几次。
    if os.environ.get("FC_REMOTE_MINIMIZE", "1") != "0":
        def _minimize_main_window():
            try:
                mw = Gui.getMainWindow()
                if mw and not mw.isMinimized():
                    mw.showMinimized()
            except Exception:
                pass
        _minimize_main_window()
        try:
            try:
                from PySide2 import QtCore as _QtCore
            except ImportError:
                from PySide import QtCore as _QtCore
            for _delay in (1000, 3000, 8000):
                _QtCore.QTimer.singleShot(_delay, _minimize_main_window)
        except Exception:
            pass

    return _server


def stop_server():
    """停止服务器"""
    global _server, _timer
    if _timer:
        _timer.stop()
        _timer = None
    if _server:
        _server.shutdown()
        _server = None
    print("[RemoteServer] Stopped.")


# ─── Auto-start when executed (热重载时若已运行则跳过) ───────────────────────
try:
    if _server is None:
        start_server()
except Exception as e:
    print(f"[RemoteServer] FATAL: {e}")
    traceback.print_exc()
