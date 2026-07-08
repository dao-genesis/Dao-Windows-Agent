"""IDE 前端（ide/vscode）契约测试：manifest 合法、动作面与桥 API 对齐、冷启动脚本存在。"""
import json
import os
import re

HERE = os.path.dirname(__file__)
REPO = os.path.abspath(os.path.join(HERE, ".."))
IDE = os.path.join(REPO, "ide", "vscode")


def test_manifest_valid_and_entrypoints():
    with open(os.path.join(IDE, "package.json"), encoding="utf-8") as fh:
        m = json.load(fh)
    assert m["main"] == "./extension.js"
    cmds = {c["command"] for c in m["contributes"]["commands"]}
    assert {"daoWin.openPanel", "daoWin.health", "daoWin.ensureBridge"} <= cmds
    props = m["contributes"]["configuration"]["properties"]
    assert props["daoWin.bridgeUrl"]["default"] == "http://127.0.0.1:9920"
    assert props["daoWin.autostart"]["default"] is True


def test_extension_covers_bridge_api_surface():
    with open(os.path.join(IDE, "extension.js"), encoding="utf-8") as fh:
        src = fh.read()
    for endpoint in (
        "/api/health", "/api/apps", "/api/session.create", "/api/session.list",
        "/api/session.open_app", "/api/session.invoke", "/api/search_verbs",
    ):
        assert endpoint in src, f"extension.js 缺桥端点 {endpoint}"
    # 自启桥必须用打包捆入的 runtime（零配置冷启动本源）
    assert re.search(r'join\(context\.extensionPath,\s*"runtime"\)', src)
    assert '"-m", "bridge.server"' in src


def test_coldstart_orchestrator_present():
    up = os.path.join(REPO, "coldstart", "up.sh")
    assert os.path.isfile(up)
    with open(up, encoding="utf-8") as fh:
        src = fh.read()
    for stage in ("preflight.sh", "fetch_media.sh", "build_image.sh", "run_vm.sh", "19920"):
        assert stage in src


def test_build_image_bundles_vsix():
    with open(os.path.join(REPO, "coldstart", "windows-sim", "build_image.sh"), encoding="utf-8") as fh:
        src = fh.read()
    assert "dao-windows-agent-" in src and "vsix" in src


def test_firstlogon_provisions_vscode_extension():
    with open(os.path.join(REPO, "coldstart", "windows-sim", "scripts", "firstlogon.ps1"), encoding="utf-8") as fh:
        src = fh.read()
    assert "Microsoft.VisualStudioCode" in src
    assert "--install-extension" in src
    assert "--source winget" in src  # 防 msstore 源歧义（真机踩坑）
