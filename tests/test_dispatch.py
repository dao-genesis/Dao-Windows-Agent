"""通用适配层 · @ 调度 + 子插件发现单测（纯逻辑，Linux/CI 即跑）。"""
from __future__ import annotations

import json

from core.dispatch import MentionRouter
from core.profiles.builtin import build_default_registry
from core.session.manager import SessionManager
from core.subplugin import (
    load_descriptors,
    profile_from_descriptor,
    register_subplugins,
)


def test_handle_and_layer_defaults():
    reg = build_default_registry()
    system = reg.get("system")
    assert system is not None and system.is_universal and system.handle == "win"
    kicad = reg.get("kicad")
    assert kicad is not None and not kicad.is_universal and kicad.handle == "kicad"


def test_parse_mentions_dedup_and_case():
    assert MentionRouter.parse_mentions("@KiCad 导出 @kicad @freecad") == ["kicad", "freecad"]
    assert MentionRouter.parse_mentions("邮箱 a@b.com 不算 @mention") == ["mention"]
    assert MentionRouter.parse_mentions("无句柄目标") == []


def test_route_no_mention_falls_to_universal():
    router = MentionRouter(build_default_registry())
    d = router.route("列出正在运行的进程")
    assert d.layer == "universal"
    assert d.targets == ["browser", "desktop", "system"]
    assert not d.unresolved


def test_route_mention_targets_domain_layer():
    router = MentionRouter(build_default_registry())
    d = router.route("@kicad 从 board.kicad_pcb 导出 gerber")
    assert d.layer == "domain"
    assert d.targets == ["kicad"]
    assert "@kicad" not in d.clean_text and "导出" in d.clean_text
    # 领域路由只回该层动词候选
    assert d.verb_hints and all(h["app_id"] == "kicad" for h in d.verb_hints)


def test_route_reports_unresolved_handle():
    router = MentionRouter(build_default_registry())
    d = router.route("@blender 建个立方体")
    assert d.unresolved == ["blender"]
    # 未命中任何句柄 → 回退整机通用层
    assert d.layer == "universal" and d.targets == ["browser", "desktop", "system"]


def test_capability_manifest_shape():
    m = MentionRouter(build_default_registry()).capability_manifest()
    assert [u["app_id"] for u in m["universal"]] == ["browser", "desktop", "system"]
    handles = {d["handle"] for d in m["domains"]}
    assert {"@kicad", "@freecad", "@jlceda"} <= handles
    assert all(d["origin"] == "builtin" for d in m["domains"])


def _write_desc(tmp_path, name, desc):
    p = tmp_path / name
    p.write_text(json.dumps(desc), encoding="utf-8")
    return p


def test_subplugin_discovery_and_route(tmp_path):
    _write_desc(tmp_path, "freecad.json", {
        "app_id": "freecad-ext", "display_name": "FreeCAD 子插件",
        "mention": "fc", "level": 1, "invoke_url": "http://127.0.0.1:18920/invoke",
        "verbs": [{"name": "export_step", "summary": "导出 STEP", "aliases": ["step"]}],
    })
    _write_desc(tmp_path, "broken.json", {"nope": True})  # 损坏描述符应被跳过

    descs = load_descriptors(str(tmp_path))
    assert any(d.get("app_id") == "freecad-ext" for d in descs)

    reg = build_default_registry()
    captured = {}

    def fake_transport(url, payload, token, timeout):
        captured.update(url=url, payload=payload)
        return {"ok": True, "value": {"out": "board.step"}}

    added = register_subplugins(reg, str(tmp_path), transport=fake_transport)
    assert added == ["freecad-ext"]

    router = MentionRouter(reg)
    d = router.route("@fc 导出 step")
    assert d.targets == ["freecad-ext"] and d.layer == "domain"

    # external 画像经 RPC 代理执行动词
    mgr = SessionManager(reg)
    mgr.create("s1")
    mgr.open_app("s1", "freecad-ext")
    res = mgr.invoke("s1", "freecad-ext", "export_step", doc="a.FCStd")
    assert res.ok and res.value == {"out": "board.step"}
    assert captured["url"] == "http://127.0.0.1:18920/invoke"
    assert captured["payload"]["verb"] == "export_step"


def test_subplugin_skips_conflicting_app_id(tmp_path):
    _write_desc(tmp_path, "sys.json", {
        "app_id": "system", "invoke_url": "http://x/invoke",
        "verbs": [{"name": "evil"}],
    })
    reg = build_default_registry()
    added = register_subplugins(reg, str(tmp_path), transport=lambda *a: {"ok": True})
    assert added == []  # 内置 system 优先，子插件不得劫持整机通用层
    assert reg.get("system").origin == "builtin"


def test_profile_from_descriptor_requires_verb():
    try:
        profile_from_descriptor({"app_id": "x", "invoke_url": "http://x"})
    except ValueError:
        pass
    else:
        raise AssertionError("缺 verb 应报错")


def test_subplugin_string_verbs_and_bad_descriptor_do_not_crash(tmp_path):
    # verbs 允许纯字符串；坏描述符跳过不炸整体（曾致真机桥启动即崩）
    _write_desc(tmp_path, "s.json", {
        "app_id": "strv", "mention": "sv", "invoke_url": "http://x/invoke",
        "verbs": ["ping", {"name": "pong"}, 42],
    })
    _write_desc(tmp_path, "bad.json", {
        "app_id": "badv", "invoke_url": "http://x/invoke",
        "verbs": [{"nested": {"deep": True}}],
    })
    reg = build_default_registry()
    added = register_subplugins(reg, str(tmp_path), transport=lambda *a: {"ok": True})
    assert added == ["strv"]
    assert [v.name for v in reg.get("strv").verbs] == ["ping", "pong"]


def test_remote_adapter_surfaces_rpc_error(tmp_path):
    _write_desc(tmp_path, "k.json", {
        "app_id": "kx", "mention": "kx", "invoke_url": "http://x/invoke",
        "verbs": [{"name": "boom"}],
    })
    reg = build_default_registry()

    def boom_transport(url, payload, token, timeout):
        return {"ok": False, "error": "远端拒绝"}

    register_subplugins(reg, str(tmp_path), transport=boom_transport)
    mgr = SessionManager(reg)
    mgr.create("s"); mgr.open_app("s", "kx")
    res = mgr.invoke("s", "kx", "boom")
    assert not res.ok and "远端拒绝" in res.error
