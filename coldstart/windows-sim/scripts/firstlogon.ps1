# 首登置备（无人值守安装末尾自动执行）。
# 装 virtio guest-agent、开 RDP、装 Python，落地机控桥（后续由 bridge/ 提供）。
$ErrorActionPreference = 'SilentlyContinue'
$log = "$env:SystemDrive\dao-firstlogon.log"
function Log($m){ "$([DateTime]::Now.ToString('s')) $m" | Tee-Object -FilePath $log -Append }

Log "== Dao first-logon start =="

# 1) 确保 RDP 开、NLA 关（便于 Agent 从宿主 loopback RDP 接入隔离会话）
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' -Name UserAuthentication -Value 0
Enable-NetFirewallRule -DisplayGroup 'Remote Desktop'
Log "RDP enabled"

# 2) QEMU guest agent（virtio-win.iso 内），供宿主 QMP 无头管控
$qga = Get-ChildItem 'E:\guest-agent\qemu-ga-x86_64.msi','F:\guest-agent\qemu-ga-x86_64.msi' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($qga) { Start-Process msiexec -ArgumentList "/i `"$($qga.FullName)`" /qn" -Wait; Log "qemu-ga installed" }

# 3) Python（winget，供机控桥与级别① 适配器在 guest 内运行）
try { winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements; Log "python installed (winget)" } catch { Log "winget python skipped: $_" }
function Resolve-Python {
  foreach ($p in @('C:\Program Files\Python312\python.exe','C:\Program Files\Python313\python.exe')) { if (Test-Path $p) { return $p } }
  $c = Get-Command python -ErrorAction SilentlyContinue; if ($c) { return $c.Source }
  return $null
}
$py = Resolve-Python
if (-not $py) {
  # winget 不可用时离线兜底：官网静默安装
  try {
    $inst = "$env:TEMP\py312.exe"
    Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $inst
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
  $token = if ($env:DAO_WIN_TOKEN) { $env:DAO_WIN_TOKEN } else { 'dao-win-lab' }
  # 级别② 实机 driver 依赖（装不上不阻断：bridge 自动退回 dry-run）
  # 必须装到全局 site-packages（user-site 的 pywin32 DLL 不落位，import 必败）
  try { & $py -m pip install --quiet --no-user pywinauto; Log "pywinauto installed (level2 driver live)" } catch { Log "pywinauto skipped: $_" }
  New-NetFirewallRule -DisplayName 'DaoBridge9920' -Direction Inbound -Protocol TCP -LocalPort 9920 -Action Allow -ErrorAction SilentlyContinue | Out-Null
  # 登录自启：无界面常驻，绑 0.0.0.0:9920（宿主 hostfwd 19920→9920 可达）
  $start = "$dst\start-bridge.ps1"
@"
`$env:DAO_WIN_TOKEN='$token'
Set-Location '$dst'
& '$py' -m bridge.server --host 0.0.0.0 --port 9920
"@ | Set-Content -Encoding UTF8 $start
  # SYSTEM + 开机触发：桥不依赖交互登录会话，注销/RDP 断连均不掉（会话隔离桌面由桥自行 CreateDesktop）
  $action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$start`"" -WorkingDirectory $dst
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  $penv    = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  Register-ScheduledTask -TaskName 'DaoBridge' -Action $action -Trigger $trigger -Settings $set -Principal $penv -Force | Out-Null
  # 立即拉起一次（本次登录即可用，无需等下次登录）
  Start-Process $py -ArgumentList '-m','bridge.server','--host','0.0.0.0','--port','9920' -WorkingDirectory $dst -WindowStyle Hidden
  Log "bridge deployed + scheduled (token=$token, port 9920)"
} else {
  Log "bridge deploy skipped (src=$src py=$py)"
}

Log "== Dao first-logon done =="
