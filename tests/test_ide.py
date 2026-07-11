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


def test_extension_multi_account_surface():
    with open(os.path.join(IDE, "package.json"), encoding="utf-8") as fh:
        m = json.load(fh)
    cmds = {c["command"] for c in m["contributes"]["commands"]}
    assert {"daoWin.openAccountDesktop", "daoWin.accountCreate",
            "daoWin.accountList", "daoWin.accountDestroy"} <= cmds
    with open(os.path.join(IDE, "extension.js"), encoding="utf-8") as fh:
        src = fh.read()
    # 多账号桌面：面板按 key（账号名/ide）多开、按账号铸令牌、账号管理走桥 /api/account.*
    assert "desktopPanels" in src and "fetchAccounts" in src
    assert "account=" in src  # 按账号取 token
    for endpoint in ("/api/account.create", "/api/account.list", "/api/account.destroy"):
        assert endpoint in src, f"extension.js 缺账号端点 {endpoint}"


def test_tunnel_server_multi_account():
    with open(os.path.join(REPO, "desktop", "tunnel", "server.js"), encoding="utf-8") as fh:
        src = fh.read()
    assert "/accounts" in src and "targetForAccount" in src
    assert "ACCOUNTS_JSON" in src and "accountsRegistry" in src


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


def test_home_windows_master_control():
    """归一主页 · Windows 总控：命令注册 + RDP 五页配置收编 + 账号/子板块管理面。"""
    with open(os.path.join(IDE, "package.json"), encoding="utf-8") as fh:
        m = json.load(fh)
    cmds = {c["command"] for c in m["contributes"]["commands"]}
    assert "daoWin.home" in cmds
    with open(os.path.join(IDE, "extension.js"), encoding="utf-8") as fh:
        src = fh.read()
    # 宿主命令面
    for cmd in ("homeInfo", "rdpSave", "rdpDelete", "rdpLaunch", "subToggle", "revealDir"):
        assert f"'{cmd}'" in src or f'"{cmd}"' in src, f"缺主页命令 {cmd}"
    # 官方 mstsc .rdp 关键字段（常规/显示/本地资源/体验/高级 五页收编）
    for field in ("full address:s:", "desktopwidth:i:", "redirectclipboard:i:",
                  "connection type:i:", "authentication level:i:", "gatewayhostname:s:"):
        assert field in src, f".rdp 缺字段 {field}"
    # 非 Windows 优雅降级：仅 win32 起 mstsc
    assert "mstsc.exe" in src and 'process.platform === "win32"' in src
    # 子板块 catalog 四大领域
    for sp in ("freecad", "kicad", "jlceda", "homeassistant"):
        assert sp in src, f"子板块 catalog 缺 {sp}"


def test_mcp_tool_layer_registration():
    """底层工具融合: MCP 外壳注册进官方 mcp_config.json, 四领域动词并列官方工具。"""
    with open(os.path.join(IDE, "package.json"), encoding="utf-8") as fh:
        m = json.load(fh)
    cmds = {c["command"] for c in m["contributes"]["commands"]}
    assert "daoWin.mcpRegister" in cmds
    with open(os.path.join(IDE, "extension.js"), encoding="utf-8") as fh:
        src = fh.read()
    assert 'require("./dao-mcp")' in src
    with open(os.path.join(IDE, "dao-mcp.js"), encoding="utf-8") as fh:
        mcp = fh.read()
    assert '"-m", "bridge.mcp"' in mcp and "mcp_config.json" in mcp
    assert "RefreshMcpServers" in mcp  # 官方 LS 热刷新


def test_mcp_node_selftest():
    """dao-mcp 纯逻辑 node 自检(merge/entry/落盘幂等)。"""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node 不可用")
    r = subprocess.run([node, os.path.join(IDE, "test", "dao-mcp.test.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
