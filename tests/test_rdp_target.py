"""RDP 回环目标发现测试（core/rdp_target）。

锁死：.rdp 文件解析、cmdkey 解析、合并映射、回环分配。
全部经 fake 数据在 Linux 上验（不碰真机）。
"""
import os
import textwrap

from core.rdp_target import RdpTargetRegistry, _parse_one_rdp, RdpTarget


# —— .rdp 文件解析 ——
def test_parse_rdp_file(tmp_path):
    rdp = tmp_path / "RDP_ai.rdp"
    rdp.write_text(textwrap.dedent("""\
        screen mode id:i:2
        full address:s:127.0.0.8
        username:s:ai
        authentication level:i:0
        prompt for credentials on client:i:0
    """), encoding="utf-8")
    t = _parse_one_rdp(str(rdp))
    assert t is not None
    assert t.username == "ai"
    assert t.loopback_ip == "127.0.0.8"
    assert t.loopback_index == 8


def test_parse_rdp_file_derives_name_from_filename(tmp_path):
    rdp = tmp_path / "RDP_zhou.rdp"
    rdp.write_text("full address:s:127.0.0.3\n", encoding="utf-8")
    t = _parse_one_rdp(str(rdp))
    assert t is not None
    assert t.username == "zhou"


def test_parse_rdp_file_non_loopback_ignored(tmp_path):
    rdp = tmp_path / "remote.rdp"
    rdp.write_text("full address:s:192.168.1.100\nusername:s:test\n", encoding="utf-8")
    assert _parse_one_rdp(str(rdp)) is None


# —— cmdkey 解析 ——
_CMDKEY_OUTPUT = """\
Currently stored credentials:

    Target: TERMSRV/127.0.0.3
    Type: Generic
    User: zhou
    Local machine persistence

    Target: TERMSRV/127.0.0.8
    Type: Generic
    User: ai
    Local machine persistence

    Target: TERMSRV/DESKTOP-MASTER
    Type: Generic
    User: Administrator
    Local machine persistence
"""


def test_cmdkey_parsing():
    reg = RdpTargetRegistry(
        runner=lambda argv: (0, _CMDKEY_OUTPUT, ""))
    mapping = reg._parse_cmdkey()
    assert mapping["127.0.0.3"] == "zhou"
    assert mapping["127.0.0.8"] == "ai"
    # Non-loopback entries are ignored
    assert "DESKTOP-MASTER" not in str(mapping.keys())


# —— 发现 + 合并 ——
def test_discover_merges_rdp_and_cmdkey(tmp_path):
    # Create .rdp files
    for name, ip in [("ai", "127.0.0.8"), ("zhou", "127.0.0.3"), ("daovm", "127.0.0.6")]:
        rdp = tmp_path / f"RDP_{name}.rdp"
        rdp.write_text(f"full address:s:{ip}\nusername:s:{name}\n", encoding="utf-8")

    reg = RdpTargetRegistry(
        runner=lambda argv: (0, _CMDKEY_OUTPUT, ""),
        rdp_search_dirs=[str(tmp_path)])
    result = reg.discover()
    assert result["ok"] is True
    targets = {t["username"]: t for t in result["targets"]}
    # ai: from both rdp and cmdkey
    assert targets["ai"]["loopback_ip"] == "127.0.0.8"
    assert targets["ai"]["has_credential"] is True
    assert targets["ai"]["rdp_file"] != ""
    # zhou: from both
    assert targets["zhou"]["loopback_ip"] == "127.0.0.3"
    assert targets["zhou"]["has_credential"] is True
    # daovm: from rdp only (no cmdkey entry)
    assert targets["daovm"]["loopback_ip"] == "127.0.0.6"
    assert targets["daovm"]["has_credential"] is False


# —— 回环分配 ——
def test_next_free_index_skips_used():
    reg = RdpTargetRegistry(runner=lambda argv: (0, "", ""))
    # .2 and .3 used → next is .4
    idx = reg._next_free_index({"127.0.0.2", "127.0.0.3"})
    assert idx == 4


def test_next_free_index_with_gap():
    reg = RdpTargetRegistry(runner=lambda argv: (0, "", ""))
    # .2, .3, .5 used → .4 is free
    idx = reg._next_free_index({"127.0.0.2", "127.0.0.3", "127.0.0.5"})
    assert idx == 4


def test_allocate_loopback_for_new_account(tmp_path):
    for name, ip in [("ai", "127.0.0.8"), ("zhou", "127.0.0.3")]:
        rdp = tmp_path / f"RDP_{name}.rdp"
        rdp.write_text(f"full address:s:{ip}\nusername:s:{name}\n", encoding="utf-8")

    reg = RdpTargetRegistry(
        runner=lambda argv: (0, "", ""),
        rdp_search_dirs=[str(tmp_path)])
    ip = reg.allocate_loopback("newuser")
    assert ip == "127.0.0.2"  # .2 is first free (not .3 or .8)


# —— find_target ——
def test_find_target_by_name(tmp_path):
    rdp = tmp_path / "RDP_ai.rdp"
    rdp.write_text("full address:s:127.0.0.8\nusername:s:ai\n", encoding="utf-8")
    reg = RdpTargetRegistry(
        runner=lambda argv: (0, "", ""),
        rdp_search_dirs=[str(tmp_path)])
    t = reg.find_target("ai")
    assert t is not None
    assert t.loopback_ip == "127.0.0.8"
    assert reg.find_target("nonexistent") is None


# —— RdpTarget.to_dict ——
def test_target_to_dict():
    t = RdpTarget(username="ai", loopback_ip="127.0.0.8", has_credential=True)
    d = t.to_dict()
    assert d["username"] == "ai"
    assert d["loopback_index"] == 8
    assert d["has_credential"] is True
