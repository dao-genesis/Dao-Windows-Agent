"""单账号多分身·应用层隔离规格测试（core/clone/app_isolation）。

真机取证的根源缺陷：同账号两个 RDP 分身先后启动 VS Code，第二个分身的启动请求
被第一个分身的实例（per-user 单实例锁在共享 %APPDATA%）吞掉，窗口开到错误会话。
根治 = per-clone user-data-dir。本测试锁死该规格的构造逻辑与安全净化。
"""
import os
import re

from core.clone import (
    ISOLATION_REGISTRY,
    build_clone_launch,
    clone_data_root,
    isolatable_apps,
)

HERE = os.path.dirname(__file__)
REPO = os.path.abspath(os.path.join(HERE, ".."))


def test_two_clones_same_app_get_disjoint_data_dirs():
    s1 = build_clone_launch("vscode", "session-2")
    s2 = build_clone_launch("vscode", "session-3")
    assert s1.data_dir != s2.data_dir
    assert s1.data_dir == r"C:\dao_clones\session-2\vscode"
    assert s2.data_dir == r"C:\dao_clones\session-3\vscode"
    # 单实例锁作用域被收窄到分身：两份 user-data-dir 互不相同
    assert s1.args != s2.args
    assert any(a.startswith("--user-data-dir=") for a in s1.args)


def test_vscode_isolates_user_data_and_extensions():
    s = build_clone_launch("vscode", "session-2")
    assert s.isolatable
    assert f"--user-data-dir={s.data_dir}\\data" in s.args
    assert f"--extensions-dir={s.data_dir}\\ext" in s.args
    assert any("Code.exe" in e for e in s.exe_candidates)


def test_devin_desktop_same_mechanism_as_vscode():
    s = build_clone_launch("devin-desktop", "session-3")
    assert s.isolatable
    assert any(a.startswith("--user-data-dir=") for a in s.args)
    assert any(a.startswith("--extensions-dir=") for a in s.args)
    assert any("Devin" in e or "Windsurf" in e for e in s.exe_candidates)


def test_ide_apps_expose_clone_dir_to_dao_desktop_plugin():
    """VS Code/Devin Desktop 分身启动注入 DAO_CLONE_USER_DATA_DIR，
    供 dao-desktop 插件的环境共生检测把 IDE 层配置定位到分身目录。"""
    for app in ("vscode", "devin-desktop"):
        s = build_clone_launch(app, "session-2")
        assert s.env["DAO_CLONE_USER_DATA_DIR"] == f"{s.data_dir}\\data", app


def test_aliases_resolve():
    assert build_clone_launch("code", "c1").app_id == "vscode"
    assert build_clone_launch("windsurf", "c1").app_id == "devin-desktop"
    assert build_clone_launch("devin", "c1").app_id == "devin-desktop"


def test_freecad_isolates_via_env_not_args():
    s = build_clone_launch("freecad", "session-2")
    assert s.isolatable
    assert s.env == {"FREECAD_USER_HOME": f"{s.data_dir}\\home"}


def test_unknown_app_is_honestly_not_isolatable():
    s = build_clone_launch("some-legacy-app", "session-2")
    assert s.isolatable is False
    assert s.exe_candidates == []
    assert "裸启动" in s.note


def test_clone_id_sanitized_against_traversal_and_injection():
    s = build_clone_launch("vscode", r"..\..\evil; rm & |")
    assert ".." not in s.data_dir.replace(r"C:\dao_clones", "")
    assert re.fullmatch(r"[A-Za-z0-9._-]+", s.clone_id)
    assert ";" not in s.data_dir and "&" not in s.data_dir and "|" not in s.data_dir


def test_empty_clone_id_defaults():
    assert clone_data_root("", "vscode") == r"C:\dao_clones\default\vscode"


def test_extra_args_appended():
    s = build_clone_launch("vscode", "c1", extra_args=[r"C:\work\proj"])
    assert s.args[-1] == r"C:\work\proj"


def test_registry_apps_all_have_exe_candidates():
    for key in isolatable_apps():
        assert ISOLATION_REGISTRY[key].exe_candidates, key


def test_guest_launcher_script_mirrors_registry():
    """guest 侧 dao-clone-open.ps1 与 Python 注册表保持同一套软件键与隔离参数。"""
    ps1 = os.path.join(REPO, "coldstart", "windows-sim", "scripts", "dao-clone-open.ps1")
    with open(ps1, encoding="utf-8-sig") as fh:
        src = fh.read()
    for key in isolatable_apps():
        assert f"'{key}'" in src, f"dao-clone-open.ps1 缺软件键 {key}"
    assert "--user-data-dir=" in src
    assert "--extensions-dir=" in src
    assert "FREECAD_USER_HOME" in src
    assert "DAO_CLONE_USER_DATA_DIR" in src
    # 分身号默认取当前会话 id（每 RDP 分身天然唯一）
    assert "SessionId" in src


def test_build_image_bundles_launcher():
    sh = os.path.join(REPO, "coldstart", "windows-sim", "build_image.sh")
    with open(sh, encoding="utf-8") as fh:
        assert "dao-clone-open.ps1" in fh.read()


def test_firstlogon_deploys_launcher():
    ps1 = os.path.join(REPO, "coldstart", "windows-sim", "scripts", "firstlogon.ps1")
    with open(ps1, encoding="utf-8-sig") as fh:
        assert "dao-clone-open.ps1" in fh.read()
