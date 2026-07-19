"""桌面级会话经纪测试（core/desktop_router）。

锁死：一窗一路账号名幂等派生、选路映射、知情同意门禁（未授权不改机器）、
授权后建号 + 渲染描述符（默认不含密码）、可回滚 release。全部经 fake runner
+ 临时注册表在 Linux 上验（不碰真机）。
"""
import json
import os

from core.accounts import AccountManager
from core.desktop_router import DesktopRouter, account_name_for
from core.environment import EnvironmentManager


def _probe_json(**over):
    base = {
        "edition_id": "Professional",
        "product_name": "Windows 10 Pro",
        "display_version": "22H2",
        "build": "19045",
        "is_admin": True,
        "part_of_domain": False,
        "term_service": "Running",
        "fDenyTSConnections": 1,
        "fSingleSessionPerUser": 1,
        "rdpwrap_installed": False,
        "termsrv_version": "10.0.19041.1",
        "rdpwrap_build_supported": None,
    }
    base.update(over)
    return json.dumps(base)


def _router(tmp_path, **over):
    payload = _probe_json(**over)
    env = EnvironmentManager(runner=lambda s: (0, payload, ""))
    accounts = AccountManager(
        runner=lambda s: (0, "OK", ""),
        registry_path=os.path.join(str(tmp_path), "accounts.json"),
    )
    return DesktopRouter(env=env, accounts=accounts)


# —— 一窗一路账号名幂等 ——
def test_account_name_deterministic_and_valid():
    a = account_name_for("ide-window-1")
    b = account_name_for("ide-window-1")
    c = account_name_for("ide-window-2")
    assert a == b and a != c
    assert a.startswith("dao") and len(a) == 9


def test_account_name_always_valid():
    from core.accounts import valid_name
    for sid in ("", "x", "ide/with:weird chars", "窗口-中文"):
        assert valid_name(account_name_for(sid))


# —— 选路映射 ——
def test_plan_server_route_a_ready(tmp_path):
    r = _router(tmp_path, edition_id="ServerStandard",
                product_name="Windows Server 2022", fDenyTSConnections=0,
                fSingleSessionPerUser=0)
    plan = r.plan("win-1")
    assert plan["route"] == "A-rdp-multisession"
    assert plan["route_ready"] is True
    assert plan["account_name"] == account_name_for("win-1")
    # server 已多会话就绪 → 唯一待授权项是建号
    actions = {p["action"] for p in plan["pending_consent"]}
    assert actions == {"create_account"}


def test_plan_pro_admin_needs_provision_and_account(tmp_path):
    r = _router(tmp_path)  # pro, admin, rdp 关, 单会话 → 可配备
    plan = r.plan("win-1")
    assert plan["route"] == "A-rdp-multisession"
    assert plan["route_ready"] is False
    actions = {p["action"] for p in plan["pending_consent"]}
    assert actions == {"provision", "create_account"}
    assert plan["consent_ready"] is False


def test_plan_non_account_route_when_no_admin(tmp_path):
    # 无管理员 + rdp 关 → 多会话不可达 → 退桌面隔离(B)，非账号路线
    r = _router(tmp_path, is_admin=False)
    plan = r.plan("win-1")
    assert plan["route"] != "A-rdp-multisession"
    assert plan["account_name"] is None
    assert plan["consent_ready"] is True


def test_plan_non_windows_route_z(tmp_path):
    env = EnvironmentManager(runner=lambda s: (127, "", "非 Windows"))
    accounts = AccountManager(runner=lambda s: (0, "OK", ""),
                              registry_path=os.path.join(str(tmp_path), "a.json"))
    r = DesktopRouter(env=env, accounts=accounts)
    plan = r.plan("win-1")
    assert plan["route"] == "Z-coldstart"
    assert plan["account_name"] is None


# —— 知情同意门禁 ——
def test_ensure_blocks_without_provision_approval(tmp_path):
    r = _router(tmp_path)  # pro 可配备
    res = r.ensure("win-1")
    assert res["ok"] is False and res["blocked"] is True
    assert res["stage"] == "provision"


def test_ensure_blocks_account_without_approval_when_provision_done(tmp_path):
    # server 已多会话，无需 provision → 直接卡在建号门禁
    r = _router(tmp_path, edition_id="ServerStandard",
                product_name="Windows Server 2022", fDenyTSConnections=0,
                fSingleSessionPerUser=0)
    res = r.ensure("win-1", approve_provision=True)
    assert res["ok"] is False and res["stage"] == "create_account"


# —— 授权后就绪 + 渲染描述符（默认不含密码） ——
def test_ensure_ready_and_render_descriptor(tmp_path):
    r = _router(tmp_path, edition_id="ServerStandard",
                product_name="Windows Server 2022", fDenyTSConnections=0,
                fSingleSessionPerUser=0)
    res = r.ensure("win-1", approve_provision=True, approve_account=True)
    assert res["ok"] is True and res["ready"] is True
    render = res["render"]
    assert render["protocol"] == "rdp"
    params = render["guac"]["connection"]["parameters"]
    assert params["username"] == account_name_for("win-1")
    assert "password" not in params  # 默认不外泄密码


def test_render_descriptor_include_secret_has_password(tmp_path):
    r = _router(tmp_path, edition_id="ServerStandard",
                product_name="Windows Server 2022", fDenyTSConnections=0,
                fSingleSessionPerUser=0)
    r.ensure("win-1", approve_provision=True, approve_account=True)
    secret = r.render_descriptor("win-1", include_secret=True)
    assert secret["guac"]["connection"]["parameters"].get("password")


# —— 状态 + 可回滚 ——
def test_status_and_release_gated(tmp_path):
    r = _router(tmp_path, edition_id="ServerStandard",
                product_name="Windows Server 2022", fDenyTSConnections=0,
                fSingleSessionPerUser=0)
    r.ensure("win-1", approve_provision=True, approve_account=True)
    st = r.status("win-1")
    assert st["bound"] is True

    blocked = r.release("win-1")
    assert blocked["ok"] is False and blocked["blocked"] is True

    released = r.release("win-1", approve=True)
    assert released["ok"] is True
    assert r.status("win-1")["bound"] is False
