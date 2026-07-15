"""通用隔离层测试（core/clone/isolation_layer）。

锁死：档位阶梯语义、软件需求画像、最省成本/最强偏好选档、诚实边界（需求高于可用档位时
绝不假装隔离）、APPDATA 叠加规格、矩阵输出。
"""
from core.clone.isolation_layer import (
    ALL_TIERS,
    NEED_REGISTRY,
    ZERO_CONFIG_TIERS,
    IsolationTier,
    SingleInstanceKind,
    isolation_matrix,
    need_for,
    resolve_isolation,
)


def test_tier_ladder_ordering():
    assert (IsolationTier.NONE < IsolationTier.APPDATA < IsolationTier.DESKTOP
            < IsolationTier.SESSION < IsolationTier.ACCOUNT)
    assert IsolationTier.SESSION.label == "session"


def test_electron_apps_need_only_appdata():
    for app in ("vscode", "devin-desktop", "chrome", "edge"):
        assert need_for(app).min_tier == IsolationTier.APPDATA, app


def test_global_mutex_apps_need_session():
    assert need_for("wechat").min_tier == IsolationTier.SESSION
    assert need_for("office").min_tier == IsolationTier.SESSION


def test_unknown_app_conservatively_needs_session():
    need = need_for("some-legacy-app")
    assert need.kind == SingleInstanceKind.GLOBAL_MUTEX
    assert need.min_tier == IsolationTier.SESSION


def test_win11_notepad_packaged_app_needs_session():
    """Win11 打包应用激活无视 lpDesktop，HDESK 上不了 → 最低需 session（真机实测锁死）。"""
    need = need_for("notepad")
    assert need.kind == SingleInstanceKind.PACKAGED_APP
    plan = resolve_isolation("notepad", "c1")
    assert plan.isolated is False
    assert plan.min_tier == IsolationTier.SESSION
    plan2 = resolve_isolation("notepad", "c1", ALL_TIERS)
    assert plan2.isolated is True and plan2.tier == IsolationTier.SESSION


def test_aliases_flow_through():
    assert need_for("windsurf").app_id == "devin-desktop"
    assert need_for("code").app_id == "vscode"


def test_zero_config_isolates_electron_cheapest():
    plan = resolve_isolation("vscode", "session-2")  # 缺省零配置三档
    assert plan.isolated is True
    assert plan.tier == IsolationTier.APPDATA
    assert plan.placement == "shared"
    assert plan.app_launch is not None
    assert any(a.startswith("--user-data-dir=") for a in plan.app_launch.args)


def test_zero_config_cannot_isolate_global_mutex_and_says_so():
    plan = resolve_isolation("wechat", "session-2")
    assert plan.isolated is False
    assert plan.min_tier == IsolationTier.SESSION
    assert plan.tier == IsolationTier.DESKTOP  # 可用里最强，但不满足需求
    assert "无法保证" in plan.reason
    assert "rdpwrap" in plan.reason


def test_full_environment_isolates_everything():
    for app in ("vscode", "wechat", "office", "totally-unknown"):
        plan = resolve_isolation(app, "c1", available_tiers=ALL_TIERS)
        assert plan.isolated is True, app


def test_global_mutex_picks_session_not_account_by_cost():
    plan = resolve_isolation("wechat", "c1", available_tiers=ALL_TIERS)
    assert plan.tier == IsolationTier.SESSION
    assert plan.placement == "rdp-session"


def test_prefer_strongest_picks_account():
    plan = resolve_isolation("wechat", "c1", available_tiers=ALL_TIERS, prefer_strongest=True)
    assert plan.tier == IsolationTier.ACCOUNT
    assert plan.placement == "account"


def test_session_tier_still_layers_appdata_for_electron():
    """靠 SESSION 隔离 Electron 时，仍附带 per-clone user-data-dir 叠加（双保险）。"""
    plan = resolve_isolation("devin-desktop", "c7", available_tiers=ALL_TIERS,
                             prefer_strongest=True)
    assert plan.app_launch is not None
    assert plan.app_launch.data_dir.endswith(r"\c7\devin-desktop")


def test_none_always_available():
    plan = resolve_isolation("freecad", "c1", available_tiers=[IsolationTier.SESSION])
    assert plan.isolated is True  # freecad 只需 APPDATA，SESSION ≥ APPDATA 满足


def test_matrix_shape_and_honesty():
    m = isolation_matrix(["vscode", "wechat"], available_tiers=ZERO_CONFIG_TIERS)
    assert m["vscode"]["isolated"] is True
    assert m["wechat"]["isolated"] is False
    assert m["vscode"]["tier"] == "appdata"


def test_need_registry_entries_have_notes():
    for key, need in NEED_REGISTRY.items():
        assert need.note, key
        assert need.app_id == key
