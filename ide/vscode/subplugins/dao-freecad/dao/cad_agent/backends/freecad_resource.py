"""天下资源接入 (``resource.*``) — search the world's 3D-model libraries.

反者道之动: the cheapest part to make is the one you already have, and the next
cheapest is the one someone already published. This wires the standalone
``00-本源_Origin/资源探针.py`` platform clients into the agent as first-class,
fusable ops, so a build request can *search before modelling*:

* ``resource.search``    — query many libraries in parallel (Printables /
                           Sketchfab / NASA / GitHub ...), ranked, normalised.
* ``resource.platforms`` — list the searchable platforms.
* ``resource.download``  — pull a concrete model's files (where the source
                           allows direct download, e.g. Printables).

Pure Python (no FreeCAD dependency): network is reached with urllib inside the
probe clients. Every network failure is contained per-platform -- a dead source
never sinks the whole search, and malformed input is refused with a guided
ValueError before any request goes out.
"""
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

_PROBE = None
_PROBE_ERR = None


def _load_probe():
    """Import the (Chinese-named) resource probe module by file path, once."""
    global _PROBE, _PROBE_ERR
    if _PROBE is not None or _PROBE_ERR is not None:
        return _PROBE
    here = os.path.dirname(os.path.abspath(__file__))
    # cad_agent/backends -> repo root -> 00-本源_Origin/资源探针.py
    root = os.path.dirname(os.path.dirname(here))
    path = os.path.join(root, "00-本源_Origin", "资源探针.py")
    if not os.path.isfile(path):
        _PROBE_ERR = "resource probe not found at %s" % path
        return None
    try:
        spec = importlib.util.spec_from_file_location("dao_resource_probe", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PROBE = mod
    except Exception as exc:  # noqa: BLE001
        _PROBE_ERR = "resource probe import failed: %r" % (exc,)
        return None
    return _PROBE


# platforms that return real model results from this host without any token
_DEFAULT_PLATFORMS = ["printables", "sketchfab", "nasa", "github"]


def register(state):
    probe = _load_probe()

    def _platforms():
        if probe is None:
            return {}
        return getattr(probe, "PLATFORMS", {})

    def _norm(r):
        """Normalise one platform's hit into a uniform schema."""
        return {
            "platform": r.get("platform", "?"),
            "id": r.get("id"),
            "title": r.get("name") or r.get("title") or "?",
            "author": r.get("author", "?"),
            "url": r.get("url", ""),
            "downloads": int(r.get("downloads", 0) or 0),
            "likes": int(r.get("likes", r.get("stars", 0)) or 0),
            "license": r.get("license", "?"),
            "thumbnail": r.get("thumbnail", ""),
            "tags": r.get("tags", []),
            "summary": r.get("summary", ""),
        }

    def op_platforms(a):
        """List the searchable libraries (and which are token-gated)."""
        plats = _platforms()
        if not plats:
            raise ValueError(
                "resource.* unavailable: %s" % (_PROBE_ERR or "probe not loaded"))
        return {"platforms": sorted(plats.keys()),
                "default": list(_DEFAULT_PLATFORMS),
                "count": len(plats)}

    def op_search(a):
        """Search 3D-model libraries for parts matching a need.

        args: query (str), platforms ([names], default reliable no-auth set),
              limit (per-platform hit cap, default 10), timeout (s/platform)
        Returns hits ranked by popularity (downloads then likes), plus a
        per-platform status map so a dead/empty source is visible, not silent.
        """
        plats = _platforms()
        if not plats:
            raise ValueError(
                "resource.search unavailable: %s" % (_PROBE_ERR or "probe not loaded"))
        query = a.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("resource.search 'query' must be a non-empty string")
        sel = a.get("platforms", _DEFAULT_PLATFORMS)
        if isinstance(sel, str):
            sel = [sel]
        if not isinstance(sel, (list, tuple)) or not sel:
            raise ValueError(
                "resource.search 'platforms' must be a non-empty list of platform "
                "names (available: %s)" % ", ".join(sorted(plats)))
        unknown = [p for p in sel if p not in plats]
        if unknown:
            raise ValueError(
                "resource.search: unknown platform(s) %s -- available: %s"
                % (unknown, ", ".join(sorted(plats))))
        limit = a.get("limit", 10)
        if isinstance(limit, bool) or not isinstance(limit, (int, float)):
            raise ValueError("resource.search 'limit' must be a number")
        limit = max(1, min(50, int(limit)))
        timeout = a.get("timeout", 12)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("resource.search 'timeout' must be a number")
        timeout = max(2, min(60, int(timeout)))

        def _one(name):
            client = plats[name]
            try:
                hits = client.search(query, limit=limit)
                return name, [_norm(h) for h in (hits or [])], None
            except Exception as exc:  # noqa: BLE001 -- contain per-platform faults
                return name, [], "%s: %s" % (type(exc).__name__, str(exc)[:120])

        results, status = [], {}
        with ThreadPoolExecutor(max_workers=min(8, len(sel))) as ex:
            futs = {ex.submit(_one, n): n for n in sel}
            for fut in as_completed(futs, timeout=timeout * len(sel) + 5):
                name = futs[fut]
                try:
                    _, hits, err = fut.result(timeout=timeout + 2)
                except Exception as exc:  # noqa: BLE001
                    hits, err = [], "%s: %s" % (type(exc).__name__, str(exc)[:120])
                results.extend(hits)
                status[name] = {"hits": len(hits), "error": err} if err \
                    else {"hits": len(hits)}

        results.sort(key=lambda r: (r["downloads"], r["likes"]), reverse=True)
        return {"query": query, "total": len(results),
                "platforms": status, "results": results[:limit * len(sel)]}

    def op_download(a):
        """Download a concrete model's files (sources that allow it).

        args: platform (name), id (model id), out (dir, default a temp dir)
        """
        plats = _platforms()
        if not plats:
            raise ValueError(
                "resource.download unavailable: %s" % (_PROBE_ERR or "probe not loaded"))
        name = a.get("platform")
        if name not in plats:
            raise ValueError(
                "resource.download: unknown platform %r -- available: %s"
                % (name, ", ".join(sorted(plats))))
        client = plats[name]
        if not hasattr(client, "download"):
            raise ValueError(
                "resource.download: platform %r does not support direct download "
                "(open its 'url' instead)" % name)
        mid = a.get("id")
        if mid is None or (isinstance(mid, str) and not mid.strip()):
            raise ValueError("resource.download 'id' is required (from resource.search)")
        out = a.get("out")
        if out is not None and not isinstance(out, str):
            raise ValueError("resource.download 'out' must be a directory path string")
        import pathlib
        import tempfile
        out_dir = pathlib.Path(out) if out else pathlib.Path(
            tempfile.mkdtemp(prefix="dao_dl_"))
        try:
            files = client.download(str(mid), out_dir)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                "resource.download failed for %s/%s: %s: %s"
                % (name, mid, type(exc).__name__, str(exc)[:120]))
        if not files:
            raise ValueError(
                "resource.download: no downloadable files for %s/%s (it may be "
                "login-gated or have no direct STL/STEP)" % (name, mid))
        return {"platform": name, "id": mid, "files": [str(f) for f in files],
                "count": len(files), "dir": str(out_dir)}

    return {
        "resource.search": op_search,
        "resource.platforms": op_platforms,
        "resource.download": op_download,
    }
