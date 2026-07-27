"""IDE 前端（ide/vscode）契约测试：manifest 合法、动作面与桥 API 对齐、冷启动脚本存在。"""
import os

HERE = os.path.dirname(__file__)
REPO = os.path.abspath(os.path.join(HERE, ".."))
IDE = os.path.join(REPO, "ide", "vscode")


def test_ide_is_dao_one_derivation_only():
    """本源唯一：ide/vscode 不再自建插件前端，唯一交付 = dao-one(devin-remote 真源)
    经 dao-one-windows 注入 🪟 Windows 板块后打包。漂移产物(独立插件本体/独立主页/
    dao-cascade 另一支归一系面板)必须保持退役。"""
    for drift in ("extension.js", "win-home.js", "package.json", "dao-ai-base", "unify.js"):
        assert not os.path.exists(os.path.join(IDE, drift)), f"漂移产物未清理: ide/vscode/{drift}"
    with open(os.path.join(IDE, "build.sh"), encoding="utf-8") as fh:
        sh = fh.read()
    assert "devin-remote" in sh          # 从归一插件真源构建
    assert "dao-one-windows/inject.js" in sh  # 🪟 板块折入而非自建面板
    assert "pack_vsix.py" in sh


def test_injector_contract_files_present():
    d = os.path.join(IDE, "dao-one-windows")
    for name in ("inject.js", "payloads.js", "reinject.js", "pack_vsix.py"):
        assert os.path.isfile(os.path.join(d, name)), f"缺 dao-one-windows/{name}"
    with open(os.path.join(d, "payloads.js"), encoding="utf-8") as fh:
        src = fh.read()
    # 官方 mstsc 五页收编 + 账号池 + 同源桌面路由(/wdesk → guacamole-lite 4824/4823)
    for token in ("daoWinRdpFileContent", "winRdpList", "/wdesk", "4823", "4824"):
        assert token in src, f"payloads 缺 {token}"


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
    assert "dao-one-windows-" in src and "vsix" in src


def test_run_vm_uses_fresh_kvm_group_without_relogin():
    with open(os.path.join(REPO, "coldstart", "windows-sim", "run_vm.sh"), encoding="utf-8") as fh:
        src = fh.read()
    assert "KVM_VIA_GROUP" in src
    assert "exec sg kvm -c" in src


def test_firstlogon_provisions_vscode_extension():
    with open(os.path.join(REPO, "coldstart", "windows-sim", "scripts", "firstlogon.ps1"), encoding="utf-8") as fh:
        src = fh.read()
    assert "Microsoft.VisualStudioCode" in src
    assert "--install-extension" in src
    assert "--source winget" in src  # 防 msstore 源歧义（真机踩坑）


def test_firstlogon_provisions_devin_desktop_extension():
    with open(os.path.join(REPO, "coldstart", "windows-sim", "scripts", "firstlogon.ps1"), encoding="utf-8") as fh:
        src = fh.read()
    assert "win32-x64-user" in src
    assert "devin-desktop.cmd" in src
    assert "dao devin desktop extension installed" in src
    assert "vc_redist.x64.exe" in src
    assert "IsReadOnly = $false" in src


def test_coldstart_payload_cache_pipeline():
    """载荷缓存链：宿主预下(fetch_payloads) → 应答盘捆入(build_image) → guest 缓存优先(firstlogon)。"""
    fp = os.path.join(REPO, "coldstart", "windows-sim", "fetch_payloads.sh")
    assert os.path.isfile(fp)
    with open(fp, encoding="utf-8") as fh:
        fetch = fh.read()
    for payload in ("vc_redist.x64.exe", "py312.exe", "VSCodeSetup.exe",
                    "DevinUserSetup.exe", "RDPWrap.zip", "rdpwrap_community.ini"):
        assert payload in fetch
    with open(os.path.join(REPO, "coldstart", "up.sh"), encoding="utf-8") as fh:
        assert "fetch_payloads.sh" in fh.read()
    with open(os.path.join(REPO, "coldstart", "windows-sim", "build_image.sh"), encoding="utf-8") as fh:
        assert "payloads" in fh.read()
    with open(os.path.join(REPO, "coldstart", "windows-sim", "scripts", "firstlogon.ps1"), encoding="utf-8") as fh:
        fl = fh.read()
    assert "Get-Payload" in fl
    # 大件安装包走缓存优先取数（在线只是兜底）。注意：rdpwrap_community.ini 是唯一例外——
    # 它必须每次在线拉最新（见 test_firstlogon_rdpwrap_ini_fetched_fresh），故不在此列。
    for name in ("py312.exe", "vc_redist.x64.exe", "VSCodeSetup.exe",
                 "DevinUserSetup.exe", "RDPWrap.zip"):
        assert "Get-Payload '%s'" % name in fl


def test_firstlogon_rdpwrap_ini_fetched_fresh():
    """真机踩坑回归（单账号多 RDP 本源）：rdpwrap.ini 必须每次在线拉最新社区版，
    不得走 Get-Payload（缓存优先）——否则构建时捆入的旧 ini 缺当前 termsrv build 段
    （如 26100.x），三次重试只是反复拷同一份缺段文件，wrapper 加载但不打补丁，退化成单会话。
    在线失败才回退应答盘缓存；置备后须自证 dll 已挂进 termsrv 且 ini 含当前 build 段。"""
    with open(os.path.join(REPO, "coldstart", "windows-sim", "scripts", "firstlogon.ps1"),
              encoding="utf-8") as fh:
        src = fh.read()
    # 取 rdpwrap 段落
    i = src.index("RDPWrap（")
    seg = src[i:i + 6500]
    # ini 必须在线直取（Invoke-WebRequest），且不能用 Get-Payload 取 ini
    assert "sebaxakerhtc/rdpwrap.ini/master/rdpwrap.ini" in seg
    assert "Invoke-WebRequest -UseBasicParsing -Uri $iniUrl" in seg
    assert "Get-Payload 'rdpwrap_community.ini'" not in src
    # 在线失败才回退媒体缓存
    assert "payloads\\rdpwrap_community.ini" in seg
    # 必须校验当前 build 段并在替换前停服务、替换后重启重读 offset
    assert "$tsSection" in seg and "Select-String" in seg
    assert "Stop-Service TermService" in seg and "Restart-Service TermService" in seg
    # 置备后自证：dll 挂进 termsrv 进程 + 安装版 ini 含段
    assert "rdpwrap VERIFIED" in seg
    assert "fSingleSessionPerUser -Value 0" in seg


def test_coldstart_domain_payloads_and_cdp_binding():
    """真机踩坑回归：领域大件(FreeCAD/KiCad)须入缓存链；freecad_backend 须随盘落地；
    浏览器画像须由 start-bridge 绑 CDP(DAO_CDP_PORT + 无头 Edge)，否则永远 dry-run。"""
    with open(os.path.join(REPO, "coldstart", "windows-sim", "fetch_payloads.sh"),
              encoding="utf-8") as fh:
        fetch = fh.read()
    assert "FreeCAD-setup.exe" in fetch and "KiCad-setup.exe" in fetch
    with open(os.path.join(REPO, "coldstart", "windows-sim", "build_image.sh"),
              encoding="utf-8") as fh:
        build = fh.read()
    assert "dao-freecad/tools" in build
    with open(os.path.join(REPO, "coldstart", "windows-sim", "scripts", "firstlogon.ps1"),
              encoding="utf-8") as fh:
        fl = fh.read()
    assert "Get-Payload 'FreeCAD-setup.exe'" in fl
    assert "Get-Payload 'KiCad-setup.exe'" in fl
    assert '"$src\\tools"' in fl
    assert "DAO_CDP_PORT" in fl and "--remote-debugging-port=9222" in fl


def test_firstlogon_mesa_software_opengl_for_freecad():
    """真机踩坑回归（FreeCAD GPU 本源）：QEMU 虚拟显示器仅 'Microsoft Basic Display Adapter'，
    无 OpenGL 2.0，FreeCAD 带 3D 视口启动即崩。活体证明：
    · per-app 拷 opengl32.dll 进 FreeCAD\\bin 死路（Qt QSystemLibrary 只认 System32，双模块
      像素格式表互不相认，wglCreateContext 'parameter is incorrect'）；
    · GALLIUM_DRIVER=llvmpipe 机器级 env 死路（mesa 26 llvmpipe 令 wglCreateContext 返 NULL）。
    正道 = libgallium_wgl.dll 注册系统级 ICD（HKLM OpenGLDrivers），全进程透明得软件 GL 4.6。"""
    with open(os.path.join(REPO, "coldstart", "windows-sim", "fetch_payloads.sh"),
              encoding="utf-8") as fh:
        fetch = fh.read()
    # 宿主预下 + 解出 DLL 落缓存
    assert "mesa-dist-win" in fetch
    for f in ("mesa_libgallium_wgl.dll", "mesa_dxil.dll"):
        assert f in fetch
    with open(os.path.join(REPO, "coldstart", "windows-sim", "scripts", "firstlogon.ps1"),
              encoding="utf-8") as fh:
        fl = fh.read()
    # 系统级 ICD 注册（非 per-app 注入、非 llvmpipe env）
    assert "OpenGLDrivers\\MSOGL" in fl
    assert "libgallium_wgl.dll" in fl and "dxil.dll" in fl
    assert "mesa software-OpenGL installed as system ICD" in fl
    # 死路禁令：不得再置 llvmpipe 机器级 env / 不得再拷 opengl32.dll 进应用目录
    assert "SetEnvironmentVariable('GALLIUM_DRIVER'" not in fl
    assert "mesa_opengl32.dll" not in fl


def test_firstlogon_log_is_pipeline_safe():
    """真机踩坑回归：Log 绝不能用 Tee-Object 把日志行泄进管道——否则 Get-Payload 这类
    '末句返回路径' 的函数会连同 Log 行返回成 System.Object[]，令 Start-Process/Expand-Archive
    收到数组即 'Cannot convert System.Object[] to String'，全线离线安装与桥落地皆败。"""
    with open(os.path.join(REPO, "coldstart", "windows-sim", "scripts", "firstlogon.ps1"),
              encoding="utf-8") as fh:
        src = fh.read()
    log_line = next(l for l in src.splitlines() if l.strip().startswith("function Log("))
    assert "Tee-Object" not in log_line, "Log 不得用 Tee-Object（会污染函数返回值/管道）"
    assert "Add-Content" in log_line, "Log 应只写文件（Add-Content）+ 控制台，不进管道"
    assert "-Encoding UTF8" in log_line, "Log 须钉死 UTF8（PS5.1 默认 UTF-16LE，桥 read_file 读回乱码）"
    # Get-Payload 仍以 Log 记录并末句返回路径——正是被污染的高危形态，故上面的守卫必须成立
    getp = src[src.index("function Get-Payload"):]
    getp = getp[:getp.index("\n}") + 2]
    assert "Log " in getp and "return $out" in getp


def test_coldstart_runbook_handoff_doc():
    rb = os.path.join(REPO, "coldstart", "RUNBOOK.md")
    assert os.path.isfile(rb)
    with open(rb, encoding="utf-8") as fh:
        src = fh.read()
    for key in ("up.sh", "--status", "payloads", "winlab.installed", "19920", "13389"):
        assert key in src


def test_homeassistant_domain_shaper_uses_host_scope_tool_catalog():
    path = os.path.join(
        REPO,
        "ide",
        "vscode",
        "subplugins",
        "dao-ha",
        "extension.js",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    activate = src[src.index("function activate(context)"):]
    assert "DOMAIN_TOOL_SUMMARIES.map" in activate
    assert "AGENT_TOOLS.map" not in activate


def test_unified_freecad_activation_is_lazy():
    path = os.path.join(
        REPO,
        "ide",
        "vscode",
        "subplugins",
        "dao-freecad",
        "extension.js",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    activate = src[src.index("function activate(context)"):]
    assert 'if (!unifiedHost && cfg().get("autoStart"))' in activate
    assert "if (!unifiedHost) {\n    ensureShell()" in activate


def test_injector_node_selftest():
    """dao-one-windows 注入器护栏 node 自检(锚点/负载/.rdp 键/幂等/签名)。"""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node 不可用")
    r = subprocess.run([node, "--test", os.path.join(IDE, "test")],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


# ☯ 冷启动·无头登录注入（rt-flow 本源移植·彻底规避 GUI）契约测试
COLD_SCRIPTS = os.path.join(REPO, "coldstart", "windows-sim", "scripts")


def test_headless_auth_scripts_exist():
    """无头登录三件套齐备：登录核心 / CDP 注入 / 宿主编排。"""
    for name in ("devin_auth.js", "devin_inject_cdp.js", "devin_login.sh"):
        p = os.path.join(COLD_SCRIPTS, name)
        assert os.path.exists(p), f"缺无头登录脚本 {name}"


def test_headless_auth_official_endpoints():
    """登录端点 1:1 对齐 devin-remote/rt-flow 官方流（无自造/无绕过）。"""
    with open(os.path.join(COLD_SCRIPTS, "devin_auth.js"), encoding="utf-8") as fh:
        src = fh.read()
    assert "https://windsurf.com/_devin-auth/password/login" in src
    assert "https://app.devin.ai/api" in src
    assert "/users/post-auth" in src


def test_headless_auth_injection_keys():
    """注入桥键名 1:1 对齐 rt-flow buildAuthBridge（auth1_session + post-auth 守卫键）。"""
    for name in ("devin_auth.js", "devin_inject_cdp.js"):
        with open(os.path.join(COLD_SCRIPTS, name), encoding="utf-8") as fh:
            src = fh.read()
        assert "auth1_session" in src, f"{name} 缺 auth1_session"
        assert "migrated-to-unscoped-auth0-token-2025-12-18" in src, f"{name} 缺迁移键"
        assert "known-org-ids-" in src, f"{name} 缺 known-org-ids"
        assert "last-internal-org-for-external-org-v1-null" in src, f"{name} 缺 org 键"


def test_headless_auth_no_hardcoded_credentials():
    """铁律：脚本源码不得内嵌任何明文密码/凭据（账密只经环境变量传入）。"""
    import re as _re
    for name in ("devin_auth.js", "devin_inject_cdp.js", "devin_login.sh"):
        with open(os.path.join(COLD_SCRIPTS, name), encoding="utf-8") as fh:
            src = fh.read()
        assert "@outlook.com" not in src, f"{name} 疑似内嵌账号"
        # 宿主编排必须从环境读密码，不得写死
    with open(os.path.join(COLD_SCRIPTS, "devin_login.sh"), encoding="utf-8") as fh:
        sh = fh.read()
    assert "DEVIN_ACCOUNT_PASSWORD" in sh and "DEVIN_ACCOUNT_EMAIL" in sh
    # 密码不得出现在 echo/日志行
    for line in sh.splitlines():
        s = line.strip()
        if s.startswith("echo") or s.startswith("Log"):
            assert "PASSWORD" not in s, f"疑似日志泄密: {line}"


def test_headless_auth_bundle_gitignored():
    """auth 束（含 bearer）落盘路径必须已 gitignore，绝不入库。"""
    with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
        gi = fh.read()
    assert "devin_auth" in gi and ".dao/" in gi


def test_headless_auth_node_selftest():
    """devin_auth 纯逻辑 node 自检（离线·bridge 键/逃逸/形状）。"""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node 不可用")
    r = subprocess.run(
        [node, os.path.join(COLD_SCRIPTS, "test", "devin_auth.test.js")],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
