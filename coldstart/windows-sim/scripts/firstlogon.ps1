# 首登置备（无人值守安装末尾自动执行）。
# 装 virtio guest-agent、开 RDP、装 Python，落地机控桥（后续由 bridge/ 提供）。
$ErrorActionPreference = 'SilentlyContinue'
$log = "$env:SystemDrive\dao-firstlogon.log"
# 关键（真机踩坑）：Log 绝不能把日志行泄进管道/函数返回值——否则如 Get-Payload 这类
# "最后一句返回路径" 的函数会连同 Log 行一起返回成 System.Object[]，后续
# Start-Process -FilePath / Expand-Archive -Path 收到数组即报 "Cannot convert
# System.Object[] to String"，导致所有离线载荷安装与桥落地全线失败。故只写文件+控制台。
# 编码钉死 UTF8：PS5.1 的 Add-Content 默认写 UTF-16LE，经机控桥 read_file(utf-8) 读回是
# 满屏空格乱码——正是本次排障要看的日志，故统一 UTF8，运维/桥皆可直读。
function Log($m){ $line = "$([DateTime]::Now.ToString('s')) $m"; Add-Content -Path $log -Value $line -Encoding UTF8; Write-Host $line }

Log "== Dao first-logon start =="

# 置备载荷缓存（fetch_payloads.sh 预下到应答盘 payloads\）：先取随盘缓存，缺才在线下载。
$payloadDir = $null
foreach ($d in 'D:','E:','F:','G:') { if (Test-Path "$d\payloads") { $payloadDir = "$d\payloads"; break } }
if ($payloadDir) { Log "payload cache found: $payloadDir" }
function Get-Payload($name, $url) {
  if ($payloadDir -and (Test-Path "$payloadDir\$name")) {
    $out = "$env:TEMP\$name"
    Copy-Item -Force "$payloadDir\$name" $out
    Log "payload $name from media cache"
    return $out
  }
  $out = "$env:TEMP\$name"
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $out
  Log "payload $name downloaded"
  return $out
}

# 1) 确保 RDP 开、NLA 关（便于 Agent 从宿主 loopback RDP 接入隔离会话）
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' -Name UserAuthentication -Value 0
Enable-NetFirewallRule -DisplayGroup 'Remote Desktop'
Log "RDP enabled"

# 2) QEMU guest agent（virtio-win.iso 内），供宿主 QMP 无头管控。
#    必须先装 vioserial 驱动：qemu-ga MSI 不带它，PCI VEN_1AF4&DEV_1003 无驱动则
#    org.qemu.guest_agent.0 通道不通，宿主 guest-ping 恒超时（真机实测踩坑）。
$vioser = Get-ChildItem 'D:\vioserial\w11\amd64\vioser.inf','E:\vioserial\w11\amd64\vioser.inf','F:\vioserial\w11\amd64\vioser.inf','G:\vioserial\w11\amd64\vioser.inf' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($vioser) { pnputil /add-driver "$($vioser.FullName)" /install | Out-Null; Log "vioserial driver installed" } else { Log "vioserial inf not found on any drive" }
$qga = Get-ChildItem 'D:\guest-agent\qemu-ga-x86_64.msi','E:\guest-agent\qemu-ga-x86_64.msi','F:\guest-agent\qemu-ga-x86_64.msi','G:\guest-agent\qemu-ga-x86_64.msi' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($qga) { Start-Process msiexec -ArgumentList "/i `"$($qga.FullName)`" /qn" -Wait; Log "qemu-ga installed" }

# 3) Python（winget，供机控桥与级别① 适配器在 guest 内运行）
try { winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements; if ($LASTEXITCODE -eq 0) { Log "python installed (winget)" } else { Log "winget python exit=$LASTEXITCODE" } } catch { Log "winget python skipped: $_" }
function Resolve-Python {
  foreach ($p in @('C:\Program Files\Python312\python.exe','C:\Program Files\Python313\python.exe')) { if (Test-Path $p) { return $p } }
  # WindowsApps 下的 python.exe 是商店占位 stub（0 字节别名，执行只会弹商店），必须排除
  $c = Get-Command python -ErrorAction SilentlyContinue
  if ($c -and $c.Source -notmatch '\\WindowsApps\\') { return $c.Source }
  return $null
}
$py = Resolve-Python
if (-not $py) {
  # winget 不可用时离线兜底：官网静默安装
  try {
    $inst = Get-Payload 'py312.exe' 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
    Start-Process $inst -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_test=0' -Wait
    $py = Resolve-Python; Log "python installed (offline)"
  } catch { Log "offline python failed: $_" }
}

# 4) 落地机控桥（bridge/ + core/ 随应答盘带入，纯 stdlib）到 C:\dao_win，注册登录自启 + 放行 9920
$dst = 'C:\dao_win'
New-Item -ItemType Directory -Force $dst | Out-Null
$src = $null
foreach ($d in 'D:','E:','F:','G:') { if (Test-Path "$d\bridge\server.py") { $src = $d; break } }
if ($src -and $py) {
  Copy-Item -Recurse -Force "$src\bridge" "$dst\bridge"
  Copy-Item -Recurse -Force "$src\core"   "$dst\core"
  # 无头登录注入三件套（rt-flow 本源移植·彻底规避 GUI）落地，供运行时零键鼠登录 Devin。
  if (Test-Path "$src\coldstart-auth") { Copy-Item -Recurse -Force "$src\coldstart-auth" "$dst\coldstart-auth"; Log "coldstart-auth (headless login) deployed" }
  if (Test-Path "$src\tools") { Copy-Item -Recurse -Force "$src\tools" "$dst\tools"; Log "freecad_backend tools deployed" }
  Get-ChildItem -Path $dst -Recurse -Force | ForEach-Object {
    if (-not $_.PSIsContainer) { $_.IsReadOnly = $false }
  }
  $token = if ($env:DAO_WIN_TOKEN) { $env:DAO_WIN_TOKEN } else { 'dao-win-lab' }
  # 级别② 实机 driver 依赖（装不上不阻断：bridge 自动退回 dry-run）
  # 必须装到全局 site-packages（user-site 的 pywin32 DLL 不落位，import 必败）
  try {
    $vcRedist = Get-Payload 'vc_redist.x64.exe' 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
    Start-Process $vcRedist -ArgumentList '/install','/quiet','/norestart' -Wait
    Log "vc++ runtime installed"
  } catch { Log "vc++ runtime skipped: $_" }
  try { & $py -m pip install --quiet --no-user pywinauto; Log "pywinauto installed (level2 driver live)" } catch { Log "pywinauto skipped: $_" }
  New-NetFirewallRule -DisplayName 'DaoBridge9920' -Direction Inbound -Protocol TCP -LocalPort 9920 -Action Allow -ErrorAction SilentlyContinue | Out-Null
  # 登录自启：无界面常驻，绑 0.0.0.0:9920（宿主 hostfwd 19920→9920 可达）
  $start = "$dst\start-bridge.ps1"
@"
`$env:DAO_WIN_TOKEN='$token'
`$env:DAO_CDP_PORT='9222'
# 浏览器画像 CDP 绑定：无头 Edge 先起（端口未活才拉），桥启动时探测 9222 即离开 dry-run
`$edge = "`${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
if ((Test-Path `$edge) -and -not (Test-NetConnection 127.0.0.1 -Port 9222 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
  Start-Process `$edge -ArgumentList '--remote-debugging-port=9222','--user-data-dir=C:\dao_tmp\edgeprof','--headless=new','--no-first-run','about:blank'
  Start-Sleep 5
}
Set-Location '$dst'
& '$py' -m bridge.server --host 0.0.0.0 --port 9920 --subplugin-specs-dir '$dst\bridge\subplugin_specs'
"@ | Set-Content -Encoding UTF8 $start
  # 交互会话(登录用户·session>0·WinSta0)自启：桥必须与其 CreateDesktop 出的隔离桌面同处一个
  # 窗口站，隔离桌面里的窗口才可枚举/消息级输入/PrintWindow。切勿跑 SYSTEM(session0·服务窗口站)——
  # 那样 CreateProcessAsUser 起的进程落在交互 WinSta0，与 session0 里建的桌面互不可见，窗口永远枚举不到。
  $action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$start`"" -WorkingDirectory $dst
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  $penv    = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
  Register-ScheduledTask -TaskName 'DaoBridge' -Action $action -Trigger $trigger -Settings $set -Principal $penv -Force | Out-Null
  # 立即拉起一次（本次登录即可用，无需等下次登录）
  Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',$start -WorkingDirectory $dst -WindowStyle Hidden
  Log "bridge + homeassistant-ext deployed and scheduled (token=$token, port 9920)"
} else {
  Log "bridge deploy skipped (src=$src py=$py)"
}

# 5) RDPWrap（路线A 桌面级路由本源：单账号多路并行 RDP 会话）
#    在任意 Windows 版本上开启并发 RDP + 同一账号多会话，实现"一台机、一个账号、多路独立桌面"。
#    每个 IDE 窗口 = 一路 RDP 会话，经 Guacamole 送进 IDE 面板 canvas。
try {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  $rdpwrapDir = "$env:ProgramFiles\RDP Wrapper"
  # 关键（真机踩坑）：Defender 把 rdpwrap.dll 判为 HackTool 即时清除 → 装完 dll 立刻消失、
  # 表象是"装了但没装上"。故安装前先加排除目录，否则 26100.x 上必然 dll=no。
  try { Add-MpPreference -ExclusionPath $rdpwrapDir -ErrorAction SilentlyContinue } catch {}
  try { Add-MpPreference -ExclusionPath "$env:TEMP\rdpwrap" -ErrorAction SilentlyContinue } catch {}
  if (-not (Test-Path "$rdpwrapDir\rdpwrap.dll")) {
    Log "installing rdpwrap..."
    $rdpZip = Get-Payload 'RDPWrap.zip' 'https://github.com/stascorp/rdpwrap/releases/download/v1.6.2/RDPWrap-v1.6.2.zip'
    Expand-Archive -Path $rdpZip -DestinationPath "$env:TEMP\rdpwrap" -Force
    # 直接调 RDPWInst.exe -i -o（install.bat 末尾有 pause，-Wait 会永久挂起·真机踩坑）。
    # -o = 即使当前 termsrv 版本"不受支持"也强制装（新 build 如 26100.x 必需，否则直接拒装 → dll=no）。
    # 无 RDPWInst 则回退 install.bat，但用 cmd /c 并喂空 stdin 让 pause 立即返回。
    $rdpwinst = Join-Path "$env:TEMP\rdpwrap" 'RDPWInst.exe'
    if (Test-Path $rdpwinst) {
      Start-Process $rdpwinst -ArgumentList '-i','-o' -Wait -WindowStyle Hidden
    } else {
      Start-Process cmd.exe -ArgumentList '/c','"'+"$env:TEMP\rdpwrap\install.bat"+'" < NUL' -Wait -WindowStyle Hidden
    }
    if (Test-Path "$rdpwrapDir\rdpwrap.dll") { Log "rdpwrap installed (dll present)" }
    else { Log "WARN: rdpwrap.dll missing after install — 检查 Defender 排除是否生效" }
  } else {
    Log "rdpwrap already present"
  }
  # 关键：rdpwrap.ini 必须含当前 termsrv.dll build 的多会话 offset，否则 wrapper 加载但不打补丁，
  # 表现为"Another user is signed in"、并发被踢（实为单会话）。stock ini 常缺新 build（如 26100.x）段，
  # 故务必刷成社区维护版，并带重试；成功后必须重启 TermService 让 wrapper 重读 offset 才生效。
  $tsVer = (Get-Item "$env:SystemRoot\System32\termsrv.dll").VersionInfo.FileVersion
  $tsSection = '[' + (($tsVer -split ' ')[0]) + ']'
  $iniPath = "$rdpwrapDir\rdpwrap.ini"
  $iniOk = $false
  for ($i = 1; $i -le 3 -and -not $iniOk; $i++) {
    try {
      $tmpIni = Get-Payload 'rdpwrap_community.ini' 'https://raw.githubusercontent.com/sebaxakerhtc/rdpwrap.ini/master/rdpwrap.ini'
      if ((Select-String -Path $tmpIni -Pattern ([regex]::Escape($tsSection)) -SimpleMatch -Quiet)) {
        # 文件被 wrapper 占用，需先停服务再替换
        Stop-Service TermService -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Copy-Item $tmpIni $iniPath -Force
        $iniOk = $true
        Log "rdpwrap.ini updated (community); contains $tsSection for termsrv $tsVer"
      } else {
        Log "rdpwrap.ini community missing $tsSection (attempt $i); retrying"
      }
    } catch { Log "rdpwrap.ini update attempt $i failed: $_" }
    if (-not $iniOk) { Start-Sleep -Seconds 5 }
  }
  if (-not $iniOk) { Log "WARN: rdpwrap.ini lacks $tsSection — 多会话可能不生效，需人工更新 offset" }
  # Group Policy: allow multiple sessions per user (do NOT restrict to single session)
  # This enables each IDE window to get its own independent RDP session for the same account.
  Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server' -Name fSingleSessionPerUser -Value 0
  Log "rdpwrap: fSingleSessionPerUser=0 (multi-session enabled)"
  # 重启 TermService 让 rdpwrap 依据(新)ini 重新打补丁
  try {
    Restart-Service TermService -Force -ErrorAction Stop
    Log "TermService restarted (rdpwrap offsets reloaded)"
  } catch {
    Start-Service TermService -ErrorAction SilentlyContinue
    Log "TermService start after ini swap: $_"
  }
} catch { Log "rdpwrap provisioning failed: $_" }

# 6) VSCode + DAO 插件（把整台 Windows 做进 IDE：每个 IDE 窗口=一个隔离会话）
#    VSCode 经 winget 装；插件用随盘带入的 .vsix 离线安装 —— 冷启动即得可用 IDE 前端。
try {
  $codeCli = $null
  foreach ($p in @("$env:ProgramFiles\Microsoft VS Code\bin\code.cmd",
                   "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd")) {
    if (Test-Path $p) { $codeCli = $p; break }
  }
  if (-not $codeCli) {
    try { winget install -e --id Microsoft.VisualStudioCode --source winget --silent `
      --accept-source-agreements --accept-package-agreements --scope machine; Log "vscode installed (winget)" } catch { Log "winget vscode skipped: $_" }
    foreach ($p in @("$env:ProgramFiles\Microsoft VS Code\bin\code.cmd",
                     "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd")) {
      if (Test-Path $p) { $codeCli = $p; break }
    }
  }
  if (-not $codeCli) {
    # winget 不可用时离线兜底（Enterprise Eval 镜像常无 winget/msstore）：官网系统级静默安装
    try {
      $codeInst = Get-Payload 'VSCodeSetup.exe' 'https://update.code.visualstudio.com/latest/win32-x64/stable'
      Start-Process $codeInst -ArgumentList '/VERYSILENT','/NORESTART','/MERGETASKS=!runcode,addcontextmenufiles,addcontextmenufolders,associatewithfiles,addtopath' -Wait
      foreach ($p in @("$env:ProgramFiles\Microsoft VS Code\bin\code.cmd",
                       "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd")) {
        if (Test-Path $p) { $codeCli = $p; break }
      }
      Log "vscode installed (offline)"
    } catch { Log "offline vscode failed: $_" }
  }
  # 随应答盘带入的 .vsix（build_image.sh 已打包）
  $vsix = Get-ChildItem 'D:\dao-windows-agent-*.vsix','E:\dao-windows-agent-*.vsix','F:\dao-windows-agent-*.vsix','G:\dao-windows-agent-*.vsix' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($codeCli -and $vsix) {
    & $codeCli --install-extension $vsix.FullName --force
    Log "dao vscode extension installed: $($vsix.Name)"
  } else {
    Log "vscode extension skipped (code=$codeCli vsix=$vsix)"
  }
} catch { Log "vscode/extension provisioning failed: $_" }

# 7) Devin Desktop + 同一归一 VSIX（官方稳定版 user installer，无需提权）
try {
  function Resolve-DevinCli {
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Devin\bin\devin-desktop.cmd",
                     "$env:LOCALAPPDATA\Programs\Windsurf\bin\devin-desktop.cmd",
                     "$env:ProgramFiles\Devin\bin\devin-desktop.cmd",
                     "$env:ProgramFiles\Windsurf\bin\devin-desktop.cmd")) {
      if (Test-Path $p) { return $p }
    }
    $c = Get-Command devin-desktop.cmd -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
  }
  $devinCli = Resolve-DevinCli
  if (-not $devinCli) {
    $devinInst = Get-Payload 'DevinUserSetup.exe' 'https://windsurf.com/api/windsurf/download-redirect?build=win32-x64-user&isNext=false'
    Start-Process $devinInst -ArgumentList '/VERYSILENT','/NORESTART','/MERGETASKS=!runcode,addcontextmenufiles,addcontextmenufolders,associatewithfiles,addtopath' -Wait
    $devinCli = Resolve-DevinCli
    Log "devin desktop installed (stable user installer)"
  }
  if ($devinCli -and $vsix) {
    & $devinCli --install-extension $vsix.FullName --force
    Log "dao devin desktop extension installed: $($vsix.Name)"
  } else {
    Log "devin desktop extension skipped (cli=$devinCli vsix=$vsix)"
  }
} catch { Log "devin desktop provisioning failed: $_" }

# 8) 收编的领域软件本体：FreeCAD(3D) + KiCad(PCB)。winget 优先→官网静默兜底（装不上不阻断：
#    对应 profile 的 verb 会返回「可执行文件不存在」，桥其余能力照常）。嘉立创EDA(jlceda) 走 EasyEDA
#    Pro 扩展 API（sys_MessageBus/_EXTAPI_ROOT_），无独立 CLI，此处不装本体。
function Test-Cmd($paths) { foreach ($p in $paths) { if (Test-Path $p) { return $true } }; return $false }
# FreeCAD：桥探 FreeCADCmd.exe / FreeCAD.exe
$freecadPaths = @("$env:ProgramFiles\FreeCAD 0.21\bin\FreeCADCmd.exe","$env:ProgramFiles\FreeCAD 1.0\bin\FreeCADCmd.exe","$env:ProgramFiles\FreeCAD\bin\FreeCADCmd.exe")
if (-not (Test-Cmd $freecadPaths)) {
  try { winget install -e --id FreeCAD.FreeCAD --silent --accept-source-agreements --accept-package-agreements --scope machine; Log "freecad exit=$LASTEXITCODE" } catch { Log "winget freecad skipped: $_" }
  if (-not (Test-Cmd $freecadPaths)) {
    try {
      # 官方 1.0.0 资产名为 ...-installer-1.exe（NSIS，/S 静默）；旧 py311.exe 命名不存在（404）
      $fc = Get-Payload 'FreeCAD-setup.exe' 'https://github.com/FreeCAD/FreeCAD/releases/download/1.0.0/FreeCAD_1.0.0-conda-Windows-x86_64-installer-1.exe'
      Start-Process $fc -ArgumentList '/S' -Wait; Log "freecad installed (offline)"
    } catch { Log "offline freecad failed: $_" }
  }
} else { Log "freecad already present" }
# KiCad：桥探 kicad-cli.exe
$kicadPaths = @("$env:ProgramFiles\KiCad\8.0\bin\kicad-cli.exe","$env:ProgramFiles\KiCad\9.0\bin\kicad-cli.exe","$env:ProgramFiles\KiCad\bin\kicad-cli.exe")
if (-not (Test-Cmd $kicadPaths)) {
  try { winget install -e --id KiCad.KiCad --silent --accept-source-agreements --accept-package-agreements --scope machine; Log "kicad exit=$LASTEXITCODE" } catch { Log "winget kicad skipped: $_" }
  if (-not (Test-Cmd $kicadPaths)) {
    try {
      $kc = Get-Payload 'KiCad-setup.exe' 'https://kicad-downloads.s3.cern.ch/windows/stable/kicad-8.0.9-x86_64.exe'
      Start-Process $kc -ArgumentList '/S' -Wait; Log "kicad installed (offline)"
    } catch { Log "offline kicad failed: $_" }
  }
} else { Log "kicad already present" }

Log "== Dao first-logon done =="

# 收尾：仅安装阶段（unattend 光盘仍挂载）自动关机，令宿主 up.sh 以 QEMU 正常退出为装机完成信号；
# 常态启动无该光盘，不触发。
$unattendDisk = Get-ChildItem 'D:\dao-windows-agent-*.vsix','E:\dao-windows-agent-*.vsix','F:\dao-windows-agent-*.vsix','G:\dao-windows-agent-*.vsix' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($unattendDisk) { Log "install-phase shutdown in 10s"; shutdown /s /t 10 /c "dao coldstart install done" }
