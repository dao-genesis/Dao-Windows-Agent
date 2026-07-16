"""宏沉淀层单测：录制→固化→重放（含失败步拒沉淀、重放遇败即停、持久化回环）。"""
from __future__ import annotations

import pytest

from core.macros import MacroStore


def store(tmp_path) -> MacroStore:
    return MacroStore(path=str(tmp_path / "macros.json"))


def test_record_commit_and_run(tmp_path):
    st = store(tmp_path)
    st.begin("open_and_type")
    st.record_step("open_and_type", "notepad", "open", {})
    st.record_step("open_and_type", "notepad", "type_text", {"text": "hi"})
    out = st.commit("open_and_type", "打开记事本并输入")
    assert out["ok"] is True and len(out["macro"]["steps"]) == 2

    calls = []

    def invoker(app_id, verb, params):
        calls.append((app_id, verb, dict(params)))
        return {"ok": True}

    r = st.run("open_and_type", invoker)
    assert r["ok"] is True and r["ran"] == 2
    assert calls[1] == ("notepad", "type_text", {"text": "hi"})


def test_commit_refuses_failure_path(tmp_path):
    st = store(tmp_path)
    st.begin("bad")
    st.record_step("bad", "notepad", "open", {})
    st.record_step("bad", "notepad", "boom", {}, ok=False)
    out = st.commit("bad")
    assert out["ok"] is False and "失败步" in out["error"]
    assert st.list()["macros"] == []


def test_commit_requires_steps_and_recording(tmp_path):
    st = store(tmp_path)
    st.begin("empty")
    assert st.commit("empty")["ok"] is False
    with pytest.raises(KeyError):
        st.commit("never_began")
    with pytest.raises(KeyError):
        st.record_step("never_began", "a", "b")


def test_run_stops_at_first_failure(tmp_path):
    st = store(tmp_path)
    st.save("m", [{"app_id": "a", "verb": "v1"},
                  {"app_id": "a", "verb": "v2"},
                  {"app_id": "a", "verb": "v3"}])

    def invoker(app_id, verb, params):
        return {"ok": verb != "v2"}

    r = st.run("m", invoker)
    assert r["ok"] is False and r["ran"] == 2 and r["total"] == 3
    assert r["results"][-1]["verb"] == "v2" and r["results"][-1]["ok"] is False


def test_run_with_overrides_and_missing_macro(tmp_path):
    st = store(tmp_path)
    st.save("m", [{"app_id": "a", "verb": "v", "params": {"path": "x"}}])
    seen = {}

    def invoker(app_id, verb, params):
        seen.update(params)
        return {"ok": True}

    st.run("m", invoker, overrides={0: {"path": "y"}})
    assert seen["path"] == "y"
    assert st.run("nope", invoker)["ok"] is False


def test_persistence_roundtrip(tmp_path):
    p = str(tmp_path / "macros.json")
    st1 = MacroStore(path=p)
    st1.save("m", [{"app_id": "a", "verb": "v"}], "说明")
    st2 = MacroStore(path=p)
    got = st2.get("m")
    assert got is not None and got["description"] == "说明"
    assert st2.delete("m")["deleted"] is True
    assert MacroStore(path=p).get("m") is None


def test_save_rejects_invalid_steps(tmp_path):
    st = store(tmp_path)
    assert st.save("m", [{"app_id": "", "verb": ""}])["ok"] is False
    with pytest.raises(ValueError):
        st.save("", [{"app_id": "a", "verb": "v"}])
