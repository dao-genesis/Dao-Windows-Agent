"""会话激活层测试（core/session_activator）。

锁死：回环地址分配、凭据入库/清理 argv、mstsc 激活、qwinsta 解析（含真机实测样本）、
按ID/按账号注销。全部经 fake runner 在 Linux 上验（不碰真机）。
"""
from core.session_activator import SessionActivator, loopback_for, _parse_qwinsta


class FakeRunner:
    """记录每次 argv，并按预置返回值答复。"""

    def __init__(self, replies=None):
        self.calls = []
        self.replies = replies or {}

    def __call__(self, argv):
        self.calls.append(argv)
        key = argv[0]
        return self.replies.get(key, (0, "", ""))


# —— 回环地址分配 ——
def test_loopback_for_maps_from_2():
    assert loopback_for(0) == "127.0.0.2"
    assert loopback_for(1) == "127.0.0.3"
    assert loopback_for(7) == "127.0.0.9"


def test_loopback_for_out_of_range():
    import pytest
    with pytest.raises(ValueError):
        loopback_for(300)


# —— 凭据入库 ——
def test_store_credential_argv():
    r = FakeRunner()
    act = SessionActivator(runner=r)
    res = act.store_credential("127.0.0.3", "zhou", "secret")
    assert res["ok"] is True
    argv = r.calls[0]
    assert argv[0] == "cmdkey"
    assert argv[1] == "/generic:TERMSRV/127.0.0.3"
    assert argv[2] == "/user:zhou"
    assert argv[3] == "/pass:secret"


def test_store_credential_rejects_bad_name():
    act = SessionActivator(runner=FakeRunner())
    assert act.store_credential("127.0.0.3", "bad name!", "x")["ok"] is False


def test_store_credential_rejects_bad_ip():
    act = SessionActivator(runner=FakeRunner())
    assert act.store_credential("999.1.1.1", "zhou", "x")["ok"] is False


def test_clear_credential_argv():
    r = FakeRunner()
    act = SessionActivator(runner=r)
    res = act.clear_credential("127.0.0.5")
    assert res["ok"] is True
    assert r.calls[0] == ["cmdkey", "/delete:TERMSRV/127.0.0.5"]


# —— 激活 ——
def test_activate_launches_mstsc():
    r = FakeRunner()
    act = SessionActivator(runner=r)
    res = act.activate("127.0.0.8")
    assert res["ok"] is True and res["launched"] is True
    assert r.calls[0] == ["mstsc", "/v:127.0.0.8"]


def test_activate_bad_ip():
    act = SessionActivator(runner=FakeRunner())
    assert act.activate("nope")["ok"] is False


# —— qwinsta 解析（真机实测样本：DESKTOP-MASTER 双会话并发） ——
_QWINSTA_REAL = """ SESSIONNAME               USERNAME                 ID  STATE   TYPE        DEVICE
 services                                            0  Disc
>console                   Administrator             1  Active
 rdp-tcp#0                 ai                        4  Active
 rdp-tcp                                         65536  Listen
"""


def test_parse_qwinsta_real_sample():
    rows = _parse_qwinsta(_QWINSTA_REAL)
    by_user = {s.username: s for s in rows if s.username}
    assert by_user["Administrator"].id == "1"
    assert by_user["Administrator"].active is True
    assert by_user["Administrator"].sessionname == "console"
    assert by_user["ai"].id == "4"
    assert by_user["ai"].active is True
    assert by_user["ai"].sessionname == "rdp-tcp#0"
    # listen/disc 行无用户名，state 正确
    states = {s.sessionname: s.state for s in rows}
    assert states["rdp-tcp"] == "Listen"
    assert states["services"] == "Disc"


def test_list_sessions_counts_active():
    r = FakeRunner({"qwinsta": (0, _QWINSTA_REAL, "")})
    act = SessionActivator(runner=r)
    res = act.list_sessions()
    assert res["ok"] is True
    assert res["active_count"] == 2  # Administrator + ai


def test_find_session_by_user():
    r = FakeRunner({"qwinsta": (0, _QWINSTA_REAL, "")})
    act = SessionActivator(runner=r)
    s = act.find_session("ai")
    assert s and s["id"] == "4" and s["active"] is True
    assert act.find_session("nobody") is None


# —— 注销 ——
def test_logoff_by_id():
    r = FakeRunner()
    act = SessionActivator(runner=r)
    res = act.logoff("4")
    assert res["ok"] is True
    assert r.calls[0] == ["logoff", "4"]


def test_logoff_bad_id():
    act = SessionActivator(runner=FakeRunner())
    assert act.logoff("abc")["ok"] is False


def test_logoff_user_resolves_id():
    r = FakeRunner({"qwinsta": (0, _QWINSTA_REAL, "")})
    act = SessionActivator(runner=r)
    res = act.logoff_user("ai")
    assert res["ok"] is True
    # 第二次调用应是 logoff 4
    assert ["logoff", "4"] in r.calls


def test_logoff_user_absent():
    r = FakeRunner({"qwinsta": (0, _QWINSTA_REAL, "")})
    act = SessionActivator(runner=r)
    res = act.logoff_user("ghost")
    assert res["ok"] is True and res.get("already_absent") is True
