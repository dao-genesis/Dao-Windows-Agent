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
try { winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements; Log "python installed" } catch { Log "python install skipped: $_" }

# 4) 占位：拉起机控桥（后续 bridge/ 落地后在此 clone+启动 + 注册计划任务自启）
#    New-Item -ItemType Directory C:\dao_win -Force | Out-Null
#    ... git clone / start daemon / Register-ScheduledTask AtLogon ...

Log "== Dao first-logon done =="
