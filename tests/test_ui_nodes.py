"""ui_tree 结构化之眼单测：异构节点归一 + 过滤 + 经 osctl driver 全链路。"""
from __future__ import annotations

from core.adapter.osctl_driver import OsctlExecutor
from core.profiles.builtin import build_default_registry
from core.session.manager import SessionManager
from core.ui_nodes import normalize_node, normalize_nodes, summarize


def test_normalize_osctl_children_shape():
    # osctl uia_children 形状：{name, type, aid, help}（无 rect）
    nodes = normalize_nodes([
        {"name": "保存", "type": "Button", "aid": "SaveBtn", "help": "保存文件"},
        {"name": "正文", "type": "Document", "aid": "", "help": ""},
    ])
    assert nodes[0] == {"id": 0, "name": "保存", "control_type": "Button",
                        "automation_id": "SaveBtn", "help": "保存文件",
                        "rect": None, "actionable": True}
    assert nodes[1]["control_type"] == "Document" and nodes[1]["actionable"] is True


def test_normalize_alt_shapes_and_rect():
    # 其他驱动形状：control_type + rect dict / rect 元组
    n1 = normalize_node({"control_type": "Text", "name": "说明",
                         "rect": {"x": 1, "y": 2, "w": 3, "h": 4}})
    assert n1["rect"] == {"x": 1, "y": 2, "w": 3, "h": 4}
    assert n1["actionable"] is False  # 纯展示类不算可交互
    n2 = normalize_node({"type": "Button", "rect": (10, 20, 30, 40)})
    assert n2["rect"] == {"x": 10, "y": 20, "w": 30, "h": 40}
    # 坏 rect 如实 None，绝不臆造
    assert normalize_node({"type": "Button", "rect": "bogus"})["rect"] is None
    assert normalize_node({"type": "Button", "rect": (1, 2)})["rect"] is None


def test_filters_and_renumbering():
    children = [
        {"name": "保存", "type": "Button"},
        {"name": "取消", "type": "Button"},
        {"name": "标题", "type": "Text"},
        {"name": "", "type": "Edit", "aid": "SearchBox"},
    ]
    by_type = normalize_nodes(children, control_type="button")
    assert [n["name"] for n in by_type] == ["保存", "取消"]
    assert [n["id"] for n in by_type] == [0, 1]  # 过滤后重编号
    # name 过滤同时命中 automation_id
    by_name = normalize_nodes(children, name="searchbox")
    assert len(by_name) == 1 and by_name[0]["control_type"] == "Edit"
    act = normalize_nodes(children, actionable_only=True)
    assert {n["control_type"] for n in act} == {"Button", "Edit"}
    # 垃圾输入如实回空
    assert normalize_nodes(None) == []
    assert normalize_nodes([1, "x"]) == []


def test_summarize_counts():
    nodes = normalize_nodes([
        {"type": "Button"}, {"type": "Button"}, {"type": "Text"}, {},
    ])
    s = summarize(nodes)
    assert s["Button"] == 2 and s["Text"] == 1 and s["(unknown)"] == 1


class FakeOsctl:
    """仅覆盖 tree 链路所需（activate → uia_children）。"""

    def list_windows(self):
        return [{"id": 7, "title": "Untitled - Notepad"}]

    def activate_window(self, win):
        return True

    def uia_children(self, win):
        return [
            {"name": "文件", "type": "MenuItem", "aid": "", "help": ""},
            {"name": "正文", "type": "Document", "aid": "TextBox", "help": ""},
            {"name": "状态栏", "type": "StatusBar", "aid": "", "help": ""},
        ]


def test_ui_tree_end_to_end_normalized_and_filtered(tmp_path):
    ex = OsctlExecutor(FakeOsctl())
    reg = build_default_registry(autodetect_uia=False, vision_grounder=ex.run)
    mgr = SessionManager(reg, root=str(tmp_path))
    mgr.create("s1")
    mgr.open_app("s1", "desktop")
    r = mgr.invoke("s1", "desktop", "ui_tree", title="notepad", control_type="Document")
    assert r.ok, r.error
    tree = r.value["results"][-1]
    assert tree["op"] == "tree" and tree["count"] == 1
    assert tree["nodes"][0]["name"] == "正文"
    assert tree["nodes"][0]["actionable"] is True
    assert tree["summary"] == {"Document": 1}
    # 未过滤时全量归一
    r2 = mgr.invoke("s1", "desktop", "ui_tree", title="notepad")
    assert r2.ok and r2.value["results"][-1]["count"] == 3
