"""Whole-project awareness (the ``project.*`` tool group).

The missing closed loop: an agent working on code can ``cat`` a source file
and instantly hold the entire program in mind; an agent working on a CAD
model had no equivalent — it groped object by object, blind-men-and-elephant
style. This module is that equivalent: **one call returns the complete,
current truth of the modelling project**, structured for a machine and
rendered for a mind.

- ``project.state``  one call -> the full structured JSON: document meta,
  every shaped object (dims, volume, placement, feature census, dependency
  links), spreadsheet parameters, pairwise relations, and a diagnosed issue
  list (recompute errors, null shapes, interference).
- ``project.brief``  the same truth rendered as one readable markdown
  document — "the source file of the model". Reading it top to bottom is
  reading the project.
- ``project.save_brief``  persist the brief to disk so any out-of-process
  agent can pick it up.
- ``project.snapshot`` / ``project.diff``  the model's ``git diff``: snapshot
  the current truth under a label, then later diff the live model against it
  (or one label against another) — objects added/removed, volume/placement/
  feature drift, issues appearing or resolving. A code agent reads diffs to
  see what a change really did; now the CAD agent does the same.

不出於戶，以知天下。 Runs inside freecadcmd (headless) and in the GUI.
"""
import time

import freecad_percept as _pc

_SCAFFOLDING = {"App::Origin", "App::Plane", "App::Line",
                "App::OriginGroupExtension"}


def _round(x, n=4):
    return round(float(x), n)


def _placement(obj):
    pl = getattr(obj, "Placement", None)
    if pl is None:
        return None
    q = pl.Rotation.Q
    return {"pos": [_round(pl.Base.x), _round(pl.Base.y), _round(pl.Base.z)],
            "quat": [_round(q[0]), _round(q[1]), _round(q[2]), _round(q[3])]}


def _shape_of(obj):
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return None
    return shape


def _object_entry(obj, with_features=True):
    d = {"name": obj.Name, "label": getattr(obj, "Label", ""),
         "type": obj.TypeId,
         "visible": bool(getattr(getattr(obj, "ViewObject", None),
                                 "Visibility", True))
         and bool(getattr(obj, "Visibility", True)),
         "depends_on": sorted({o.Name for o in getattr(obj, "OutList", [])}),
         "used_by": sorted({o.Name for o in getattr(obj, "InList", [])})}
    pl = _placement(obj)
    if pl:
        d["placement"] = pl
    state = [s for s in getattr(obj, "State", []) if s != "Up-to-date"]
    if state:
        d["state"] = state
    shape = _shape_of(obj)
    if shape is None:
        return d
    bb = shape.BoundBox
    d.update({
        "bbox_min": [_round(bb.XMin), _round(bb.YMin), _round(bb.ZMin)],
        "bbox_max": [_round(bb.XMax), _round(bb.YMax), _round(bb.ZMax)],
        "dims": [_round(bb.XLength), _round(bb.YLength), _round(bb.ZLength)],
        "faces": len(shape.Faces), "edges": len(shape.Edges),
        "solids": len(shape.Solids)})
    if shape.Solids:
        d["volume"] = _round(shape.Volume)
        d["area"] = _round(shape.Area)
        d["valid"] = bool(shape.isValid())
        if with_features:
            try:
                feats = _pc._recognize_features(shape)
                counts = {}
                for f in feats:
                    counts[f["type"]] = counts.get(f["type"], 0) + 1
                d["features"] = {"counts": counts,
                                 "patterns": _pc._detect_patterns(feats),
                                 "total": len(feats)}
            except Exception as exc:
                d["features"] = {"error": repr(exc)}
    return d


def _spreadsheet_params(doc):
    params = {}
    for obj in doc.Objects:
        if obj.TypeId != "Spreadsheet::Sheet":
            continue
        cells = {}
        try:
            for addr in obj.cells.getUsedCells():
                alias = obj.getAlias(addr) or addr
                try:
                    cells[alias] = obj.get(addr)
                except Exception:
                    cells[alias] = obj.getContents(addr)
        except Exception:
            pass
        params[obj.Name] = cells
    return params


def _diagnose(doc, objects, relations):
    issues = []
    for o in objects:
        if o.get("state"):
            issues.append({"kind": "recompute", "object": o["name"],
                           "detail": ",".join(o["state"])})
        if o.get("solids") and o.get("valid") is False:
            issues.append({"kind": "invalid_shape", "object": o["name"]})
        feats = o.get("features") or {}
        if feats.get("error"):
            issues.append({"kind": "feature_scan_failed", "object": o["name"],
                           "detail": feats["error"]})
    for r in relations:
        if r.get("relation") == "overlap":
            issues.append({"kind": "interference", "object": r["a"],
                           "detail": "overlaps %s by %g mm^3"
                           % (r["b"], r.get("overlap_volume", 0.0))})
    return issues


def _brief_md(st):
    m = st["meta"]
    lines = ["# 项目全貌 · %s" % m["document"],
             "",
             "- file: `%s`" % (m.get("path") or "(unsaved)"),
             "- objects: %d shaped / %d total · solids: %d"
             % (m["shaped_count"], m["object_count"], m["solid_count"]),
             "- generated: %s" % m["generated"], ""]
    issues = st.get("issues") or []
    lines.append("## 健康 (%s)" % ("OK" if not issues
                                   else "%d issue(s)" % len(issues)))
    for i in issues:
        lines.append("- **%s** `%s` %s" % (i["kind"], i["object"],
                                           i.get("detail", "")))
    lines.append("")
    lines.append("## 对象")
    for o in st["objects"]:
        head = "### %s" % o["name"]
        if o.get("label") and o["label"] != o["name"]:
            head += " (%s)" % o["label"]
        lines.append(head)
        lines.append("- type: `%s`%s" % (o["type"],
                                         "" if o.get("visible", True)
                                         else " · hidden"))
        if o.get("dims"):
            lines.append("- bbox: %gx%gx%g mm" % tuple(o["dims"]))
        if "volume" in o:
            lines.append("- volume: %g mm^3 · area: %g mm^2 · faces: %d"
                         % (o["volume"], o["area"], o["faces"]))
        feats = o.get("features") or {}
        if feats.get("counts"):
            lines.append("- features: " + ", ".join(
                "%s x%d" % kv for kv in sorted(feats["counts"].items())))
        for p in feats.get("patterns", []):
            lines.append("  - pattern: %s of %s x%d (circle r=%g)"
                         % (p.get("type"), p.get("of"), p.get("count", 0),
                            p.get("circle_radius", 0.0)))
        if o.get("placement") and any(o["placement"]["pos"]):
            lines.append("- at: %s" % (o["placement"]["pos"],))
        if o.get("depends_on"):
            lines.append("- depends on: %s" % ", ".join(o["depends_on"]))
        lines.append("")
    params = st.get("params") or {}
    if params:
        lines.append("## 参数表")
        for sheet, cells in params.items():
            lines.append("- **%s**: %s" % (
                sheet, ", ".join("%s=%s" % kv for kv in cells.items())))
        lines.append("")
    rels = st.get("relations") or []
    if rels:
        lines.append("## 空间关系")
        for r in rels:
            extra = ""
            if "overlap_volume" in r:
                extra = " (%g mm^3)" % r["overlap_volume"]
            elif r.get("relation") == "apart":
                extra = " (%g mm %s)" % (r["distance"],
                                         r.get("direction_b_from_a", ""))
            lines.append("- %s — %s: %s%s" % (r["a"], r["b"],
                                              r["relation"], extra))
        lines.append("")
    return "\n".join(lines)


def _issue_key(i):
    return (i.get("kind"), i.get("object"), i.get("detail", ""))


def _diff_states(old, new, tol=1e-3):
    o_objs = {o["name"]: o for o in old.get("objects", [])}
    n_objs = {o["name"]: o for o in new.get("objects", [])}
    added = sorted(set(n_objs) - set(o_objs))
    removed = sorted(set(o_objs) - set(n_objs))
    changed = []
    for name in sorted(set(o_objs) & set(n_objs)):
        a, b = o_objs[name], n_objs[name]
        delta = {}
        va, vb = a.get("volume"), b.get("volume")
        if va is not None and vb is not None and abs(va - vb) > tol:
            delta["volume"] = {"from": va, "to": vb,
                               "delta": _round(vb - va)}
        pa = (a.get("placement") or {}).get("pos")
        pb = (b.get("placement") or {}).get("pos")
        if pa and pb and any(abs(x - y) > tol for x, y in zip(pa, pb)):
            delta["moved"] = {"from": pa, "to": pb}
        fa = ((a.get("features") or {}).get("counts")) or {}
        fb = ((b.get("features") or {}).get("counts")) or {}
        if fa != fb:
            delta["features"] = {
                k: {"from": fa.get(k, 0), "to": fb.get(k, 0)}
                for k in sorted(set(fa) | set(fb))
                if fa.get(k, 0) != fb.get(k, 0)}
        if a.get("faces") is not None and b.get("faces") is not None \
                and a["faces"] != b["faces"]:
            delta["faces"] = {"from": a["faces"], "to": b["faces"]}
        if a.get("visible", True) != b.get("visible", True):
            delta["visible"] = {"from": a.get("visible", True),
                                "to": b.get("visible", True)}
        if delta:
            delta["object"] = name
            changed.append(delta)
    old_issues = {_issue_key(i) for i in old.get("issues", [])}
    new_issues = {_issue_key(i) for i in new.get("issues", [])}
    return {
        "added": added, "removed": removed, "changed": changed,
        "issues_new": [i for i in new.get("issues", [])
                       if _issue_key(i) not in old_issues],
        "issues_resolved": [i for i in old.get("issues", [])
                            if _issue_key(i) not in new_issues],
        "identical": (not added and not removed and not changed
                      and old_issues == new_issues),
    }


def _diff_md(d):
    if d["identical"]:
        return "无变化 — 模型与快照一致。"
    lines = []
    for n in d["added"]:
        lines.append("+ 新增 %s" % n)
    for n in d["removed"]:
        lines.append("- 移除 %s" % n)
    for c in d["changed"]:
        parts = []
        if "volume" in c:
            parts.append("volume %g -> %g (%+g mm^3)"
                         % (c["volume"]["from"], c["volume"]["to"],
                            c["volume"]["delta"]))
        if "moved" in c:
            parts.append("moved %s -> %s" % (c["moved"]["from"],
                                             c["moved"]["to"]))
        if "features" in c:
            parts.append("features " + ", ".join(
                "%s %d->%d" % (k, v["from"], v["to"])
                for k, v in c["features"].items()))
        if "faces" in c:
            parts.append("faces %d->%d" % (c["faces"]["from"],
                                           c["faces"]["to"]))
        if "visible" in c:
            parts.append("visible %s->%s" % (c["visible"]["from"],
                                             c["visible"]["to"]))
        lines.append("~ %s: %s" % (c["object"], "; ".join(parts)))
    for i in d["issues_new"]:
        lines.append("! 新问题 %s `%s` %s" % (i.get("kind"),
                                              i.get("object"),
                                              i.get("detail", "")))
    for i in d["issues_resolved"]:
        lines.append("✓ 已解决 %s `%s`" % (i.get("kind"), i.get("object")))
    return "\n".join(lines)


def register(state):
    percept = _pc.register(state)
    snapshots = {}

    def project_state(a):
        doc = state.doc
        with_features = bool(a.get("features", True))
        # Origin plumbing (App::Origin and its datum planes/axes) is FreeCAD
        # scaffolding, not design content: keep it out of the census so state
        # and diff report only what the designer actually modelled.
        objects = [_object_entry(o, with_features) for o in doc.Objects
                   if o.TypeId not in _SCAFFOLDING]
        shaped = [o for o in objects if "faces" in o]
        # Hidden objects are consumed boolean operands (the substrate hides
        # them, mirroring FreeCAD's own Part booleans): keep them listed but
        # out of the live-geometry census so they cannot raise phantom
        # interference against the result they were absorbed into.
        # Likewise, a part master instanced into an assembly via App::Link is
        # a prototype parked at the origin: the placed Link carries the live
        # geometry, so the master stays listed but out of the census.
        link_srcs = set()
        for obj in doc.Objects:
            if obj.TypeId == "App::Link":
                lo = getattr(obj, "LinkedObject", None)
                if lo is not None:
                    link_srcs.add(lo.Name)
        solids = [o for o in objects
                  if o.get("solids") and o.get("visible", True)
                  and o["name"] not in link_srcs]
        relations = []
        if len(solids) >= 2 and a.get("relations", True):
            try:
                relations = percept["percept.relations"](
                    {"objects": [o["name"] for o in solids]})["relations"]
            except Exception:
                relations = []
        meta = {"document": doc.Name, "path": getattr(doc, "FileName", ""),
                "object_count": len(objects), "shaped_count": len(shaped),
                "solid_count": len(solids),
                "generated": time.strftime("%Y-%m-%d %H:%M:%S")}
        st = {"meta": meta, "objects": objects,
              "params": _spreadsheet_params(doc), "relations": relations}
        st["issues"] = _diagnose(doc, objects, relations)
        st["ok"] = not st["issues"]
        return st

    def project_brief(a):
        st = project_state(a)
        return {"markdown": _brief_md(st), "ok": st["ok"],
                "issues": st["issues"],
                "object_count": st["meta"]["object_count"]}

    def project_snapshot(a):
        label = a.get("label", "last")
        if not isinstance(label, str) or not label:
            raise ValueError("project.snapshot 'label' must be a string")
        st = project_state(a)
        snapshots[label] = st
        return {"label": label, "ok": st["ok"],
                "object_count": st["meta"]["object_count"],
                "solid_count": st["meta"]["solid_count"],
                "issues": st["issues"]}

    def project_diff(a):
        base = a.get("base", "last")
        if not isinstance(base, str) or base not in snapshots:
            raise ValueError(
                "project.diff 'base' must name an existing snapshot "
                "(have: %s); take one first with project.snapshot"
                % (sorted(snapshots) or "none"))
        old = snapshots[base]
        target = a.get("target")
        if target is not None:
            if not isinstance(target, str) or target not in snapshots:
                raise ValueError(
                    "project.diff 'target' must name an existing snapshot "
                    "(have: %s)" % (sorted(snapshots) or "none"))
            new = snapshots[target]
        else:
            new = project_state(a)
        d = _diff_states(old, new)
        d["base"] = base
        d["target"] = target or "(live)"
        d["markdown"] = _diff_md(d)
        return d

    def save_brief(a):
        path = a.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("project.save_brief 'path' must be a file path")
        out = project_brief(a)
        with open(path, "w", encoding="utf-8") as f:
            f.write(out["markdown"])
        return {"path": path, "ok": out["ok"], "issues": out["issues"]}

    return {
        "project.state": project_state,
        "project.brief": project_brief,
        "project.save_brief": save_brief,
        "project.snapshot": project_snapshot,
        "project.diff": project_diff,
    }
