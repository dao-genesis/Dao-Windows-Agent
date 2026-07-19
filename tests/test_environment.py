"""任意环境适配层测试（core/environment）。

锁死：版本家族归一、探测 JSON 解析容错、逐档可达裁定（当前可用 vs 可配备）、桌面路由选路、
配备计划幂等/降级、以及"任意环境都给一条落地路径"的诚实边界。全部经 fake runner 在 Linux 上验。
"""
import json

from core.clone.isolation_layer import IsolationTier
from core.environment import (
    EnvironmentManager,
    available_tiers,
    desktop_strategy,
    edition_family,
    parse_probe,
    provision_plan,
    tier_availability,
)


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


def _mgr(**over):
    payload = _probe_json(**over)
    return EnvironmentManager(runner=lambda script: (0, payload, ""))


# —— 版本家族归一 ——
def test_edition_family_mapping():
    assert edition_family("Core") == "home"
    assert edition_family("CoreSingleLanguage") == "home"
    assert edition_family("Professional") == "pro"
    assert edition_family("Enterprise") == "enterprise"
    assert edition_family("Education") == "education"
    assert edition_family("ServerStandard") == "server"
    assert edition_family("", "Windows 10 Home") == "home"
    assert edition_family("Weird") == "unknown"


# —— 探测解析容错 ——
def test_parse_probe_non_windows():
    p = parse_probe(127, "", "powershell 不可用")
    assert p.supported is False
    assert "powershell" in p.reason


def test_parse_probe_bad_json():
    p = parse_probe(0, "not-json", "")
    assert p.supported is False


def test_parse_probe_fields_and_rdp_enabled_inversion():
    p = parse_probe(0, _probe_json(fDenyTSConnections=0), "")
    assert p.supported and p.family == "pro" and p.build == 19045
    assert p.is_admin is True
    assert p.rdp_enabled is True          # fDenyTSConnections=0 → 已开
    assert p.single_session_per_user is True


# —— 逐档可达 ——
def test_home_edition_bare_only_zero_config_now():
    """家庭版、admin、但 RDP 未开/单会话/无 RDPWrap → 当前仅零配置三档可用，SESSION 可配备。"""
    p = _mgr(edition_id="Core", product_name="Windows 11 Home").probe()
    now = available_tiers(p)
    assert IsolationTier.DESKTOP in now
    assert IsolationTier.SESSION not in now      # 当前不可用
    assert IsolationTier.ACCOUNT in now          # admin 可建账号
    prov = available_tiers(p, include_provisionable=True)
    assert IsolationTier.SESSION in prov          # 配备后可达


def test_server_with_rdp_ready_session_now():
    p = _mgr(edition_id="ServerStandard", product_name="Windows Server 2022",
             fDenyTSConnections=0, fSingleSessionPerUser=0).probe()
    now = available_tiers(p)
    assert IsolationTier.SESSION in now


def test_rdpwrap_ready_session_now():
    p = _mgr(edition_id="Professional", fDenyTSConnections=0, fSingleSessionPerUser=0,
             rdpwrap_installed=True, rdpwrap_build_supported=True).probe()
    assert IsolationTier.SESSION in available_tiers(p)


def test_non_admin_cannot_account_or_provision_session():
    p = _mgr(edition_id="Core", is_admin=False).probe()
    now = available_tiers(p)
    prov = available_tiers(p, include_provisionable=True)
    assert IsolationTier.ACCOUNT not in now
    assert IsolationTier.SESSION not in prov      # 无提权无法配备多会话
    assert IsolationTier.DESKTOP in now           # 但零配置桌面隔离仍可用


def test_domain_joined_account_tier_conservative():
    p = _mgr(part_of_domain=True).probe()
    tas = {ta.tier: ta for ta in tier_availability(p)}
    assert tas[IsolationTier.ACCOUNT].available_now is False


# —— 桌面路由选路 ——
def test_desktop_strategy_non_windows_coldstart():
    p = parse_probe(127, "", "非 Windows")
    s = desktop_strategy(p)
    assert s["route"] == "Z-coldstart" and s["ready"] is True


def test_desktop_strategy_ready_when_session_now():
    p = _mgr(edition_id="ServerStandard", fDenyTSConnections=0, fSingleSessionPerUser=0).probe()
    s = desktop_strategy(p)
    assert s["route"] == "A-rdp-multisession" and s["ready"] is True


def test_desktop_strategy_provisionable_route_a_not_ready():
    p = _mgr(edition_id="Core").probe()   # admin home，可配备
    s = desktop_strategy(p)
    assert s["route"] == "A-rdp-multisession" and s["ready"] is False


def test_desktop_strategy_non_admin_falls_to_route_b():
    p = _mgr(edition_id="Core", is_admin=False).probe()
    s = desktop_strategy(p)
    assert s["route"] == "B-virtual-display"


# —— 配备计划 ——
def test_provision_plan_home_admin_full_steps():
    p = _mgr(edition_id="Core", product_name="Windows 11 Home").probe()
    plan = provision_plan(p)
    ids = [s["id"] for s in plan["steps"]]
    assert "enable_rdp" in ids
    assert "relax_single_session" in ids
    assert "install_rdpwrap" in ids          # 家庭版需第三方多会话
    assert plan["fallback"] is not None
    # install_rdpwrap 必须标注为需人工审阅（供应链安全），不自动下载
    step = next(s for s in plan["steps"] if s["id"] == "install_rdpwrap")
    assert "人工" in step["note"] or "供应链" in step["note"]


def test_provision_plan_server_no_rdpwrap_step():
    p = _mgr(edition_id="ServerStandard", product_name="Windows Server 2022").probe()
    plan = provision_plan(p)
    ids = [s["id"] for s in plan["steps"]]
    assert "install_rdpwrap" not in ids       # server 原生多会话，无需第三方


def test_provision_plan_already_ready():
    p = _mgr(edition_id="ServerStandard", fDenyTSConnections=0, fSingleSessionPerUser=0).probe()
    plan = provision_plan(p)
    assert plan.get("already") is True and plan["steps"] == []


def test_provision_plan_non_admin_blocked_with_fallback():
    p = _mgr(edition_id="Core", is_admin=False).probe()
    plan = provision_plan(p)
    assert plan["achievable"] is False
    assert plan["blocked"]
    assert plan["fallback"]["route"] in ("B-virtual-display", "C-headless")


# —— provision(apply) 幂等执行回报 ——
def test_provision_apply_runs_steps_and_reports():
    calls = []

    def runner(script):
        if "CurrentVersion" in script and "ConvertTo-Json" in script:
            return 0, _probe_json(edition_id="Core", product_name="Windows 11 Home"), ""
        calls.append(script)
        return 0, "OK", ""

    mgr = EnvironmentManager(runner=runner)
    res = mgr.provision(apply=True)
    assert res["applied"] is True
    # enable_rdp + relax_single_session 有可执行 powershell；install_rdpwrap 亦登记
    ran = [r["id"] for r in res["results"]]
    assert "enable_rdp" in ran and "relax_single_session" in ran
    assert all(r["ok"] for r in res["results"])


def test_report_shape():
    rep = _mgr(edition_id="Core").report()
    assert set(("probe", "tiers", "available_now", "provisionable",
                "desktop_strategy", "provision_plan")).issubset(rep.keys())
    assert "none" in rep["available_now"]
