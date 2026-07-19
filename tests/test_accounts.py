"""AccountManager 单测：Windows 多账号类虚拟机内核（扩展本源第七节）。

在 Linux 上以**可注入的 fake PowerShell runner** 验证账号生命周期与注册表落盘，
不依赖真机 Windows。真机行为由脚本模板保证（模板此处一并断言含关键命令）。
"""
from __future__ import annotations

import json
import os

from bridge.service import BridgeService
from core.accounts import AccountManager, _parse_quser, valid_name


class FakeRunner:
    """记录被执行的 PS 脚本，按需返回预设 quser 输出。"""

    def __init__(self, quser_out: str = "", fail: bool = False):
        self.scripts: list[str] = []
        self.quser_out = quser_out
        self.fail = fail

    def __call__(self, script: str):
        self.scripts.append(script)
        if script.strip() == "quser":
            return 0, self.quser_out, ""
        if self.fail:
            return 1, "", "boom"
        return 0, "OK", ""


def _mgr(tmp_path, **kw) -> AccountManager:
    runner = kw.pop("runner", FakeRunner())
    return AccountManager(
        runner=runner,
        registry_path=str(tmp_path / "accounts.json"),
        **kw,
    )


def test_valid_name():
    assert valid_name("vm01") and valid_name("dao") and valid_name("a.b-c_d")
    assert not valid_name("") and not valid_name("bad name") and not valid_name("a" * 21)
    assert not valid_name("x'; rm -rf /")


def test_create_registers_and_persists(tmp_path):
    runner = FakeRunner()
    mgr = _mgr(tmp_path, runner=runner)
    res = mgr.create("vm01", password="Pw@123456")
    assert res["ok"] and res["name"] == "vm01"
    assert "Remote Desktop Users" in res["groups"]
    # 注册表落盘、含目标与凭据，供隧道读取
    reg = json.loads((tmp_path / "accounts.json").read_text(encoding="utf-8"))
    assert reg["vm01"]["username"] == "vm01"
    assert reg["vm01"]["password"] == "Pw@123456"
    assert reg["vm01"]["port"] == "3389"
    # 执行了 New-LocalUser + 加入 RDP 组
    joined = "\n".join(runner.scripts)
    assert "New-LocalUser" in joined and "Remote Desktop Users" in joined


def test_create_admin_adds_administrators(tmp_path):
    runner = FakeRunner()
    mgr = _mgr(tmp_path, runner=runner)
    res = mgr.create("adm1", admin=True)
    assert res["ok"] and "Administrators" in res["groups"]
    assert "Administrators" in "\n".join(runner.scripts)


def test_create_rejects_bad_name(tmp_path):
    mgr = _mgr(tmp_path)
    res = mgr.create("bad name")
    assert not res["ok"] and "非法账号名" in res["error"]


def test_create_failure_surfaces_error(tmp_path):
    mgr = _mgr(tmp_path, runner=FakeRunner(fail=True))
    res = mgr.create("vm01")
    assert not res["ok"] and "boom" in res["error"]
    # 失败不落注册表
    assert not os.path.exists(str(tmp_path / "accounts.json"))


def test_list_merges_registry_and_sessions(tmp_path):
    quser = (
        " USERNAME              SESSIONNAME        ID  STATE   IDLE TIME  LOGON TIME\n"
        ">dao                   console             1  Active      none   7/8/2026\n"
        " vm01                  rdp-tcp#2           2  Active         .   7/8/2026\n"
    )
    mgr = _mgr(tmp_path, runner=FakeRunner(quser_out=quser))
    mgr.create("vm01")
    out = mgr.list()
    names = {a["name"]: a for a in out["accounts"]}
    assert "vm01" in names
    # password 不外泄
    assert "password" not in names["vm01"]["target"]
    # 会话态合并进来
    assert names["vm01"]["session"] and names["vm01"]["session"]["state"] == "Active"


def test_destroy_unregisters(tmp_path):
    mgr = _mgr(tmp_path)
    mgr.create("vm01")
    assert "vm01" in json.loads((tmp_path / "accounts.json").read_text())
    res = mgr.destroy("vm01")
    assert res["ok"] and res["deleted_profile"] is True
    assert "vm01" not in json.loads((tmp_path / "accounts.json").read_text())
    assert "Remove-LocalUser" in "\n".join(mgr.runner.scripts)


def test_parse_quser():
    out = (
        " USERNAME    SESSIONNAME  ID  STATE\n"
        ">dao         console       1  Active\n"
        " vm01        rdp-tcp#2     2  Disc\n"
    )
    rows = _parse_quser(out)
    assert rows[0]["username"] == "dao" and rows[0]["id"] == "1"
    assert rows[1]["username"] == "vm01" and rows[1]["state"] == "Disc"


def test_bridge_account_routes(tmp_path):
    accounts = AccountManager(
        runner=FakeRunner(), registry_path=str(tmp_path / "accounts.json")
    )
    svc = BridgeService(root=str(tmp_path / "sess"), accounts=accounts)
    status, obj = svc.dispatch("POST", "/api/account.create", {"name": "vm01"})
    assert status == 200 and obj["ok"]
    status, obj = svc.dispatch("GET", "/api/account.list")
    assert status == 200 and any(a["name"] == "vm01" for a in obj["accounts"])
    status, obj = svc.dispatch("POST", "/api/account.destroy", {"name": "vm01"})
    assert status == 200 and obj["ok"]
    status, obj = svc.dispatch("POST", "/api/account.create", {})
    assert status == 400


def test_default_runner_degrades_gracefully_without_powershell(monkeypatch):
    """非 Windows 主机上默认 runner 不炸 FileNotFoundError，桥面返回结构化错误。"""
    import core.accounts as acc

    def _raise(*a, **k):
        raise FileNotFoundError("powershell")

    monkeypatch.setattr(acc.subprocess, "run", _raise)
    rc, out, err = acc._powershell_runner("quser")
    assert rc == 127 and "powershell 不可用" in err
