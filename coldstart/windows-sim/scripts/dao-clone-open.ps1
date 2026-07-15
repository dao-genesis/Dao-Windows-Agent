# 分身内隔离启动软件（单账号多分身根治·在分身自己的 RDP 会话里执行）。
#
# 本源：同账号多 RDP 分身，RDP 会话层已隔离，但 VS Code / Devin Desktop（Electron）等的
# 单实例锁是 per-user（落在共享 %APPDATA%）——第二个分身启动同一软件会被第一个分身的
# 实例吞掉，窗口开到错误的会话里，表象即"两个分身开同一软件缠在一起、无法隔离"。
# 根治：按分身号（默认取当前会话 id，天然每分身唯一）派生独立 user-data-dir/配置目录，
# 令单实例锁作用域从 per-user 收窄到 per-clone。逻辑与 core/clone/app_isolation.py 对齐。
#
# 用法（在分身的 RDP 会话里；默认 ExecutionPolicy 会拦本地脚本，须带 Bypass）：
#   powershell -ExecutionPolicy Bypass -File C:\dao_win\dao-clone-open.ps1 -App vscode
#   powershell -ExecutionPolicy Bypass -File C:\dao_win\dao-clone-open.ps1 -App devin-desktop -CloneId my-clone-2
param(
  [Parameter(Mandatory=$true)][string]$App,
  [string]$CloneId = '',
  [string]$Root = 'C:\dao_clones',
  [string[]]$ExtraArgs = @()
)
$ErrorActionPreference = 'Stop'

# 分身号：显式优先；否则用当前进程所在会话 id（每 RDP 分身唯一），派生 session-<id>。
if (-not $CloneId) {
  $sid = (Get-Process -Id $PID).SessionId
  $CloneId = "session-$sid"
}
# 净化为安全路径片段（对齐 _safe：仅字母数字/._-）。
$safeClone = ($CloneId -replace '[^A-Za-z0-9._-]', '_').Trim('._-'); if (-not $safeClone) { $safeClone = 'default' }
$appKey = $App.Trim().ToLower()
$alias = @{ 'code'='vscode'; 'vs-code'='vscode'; 'devin'='devin-desktop'; 'windsurf'='devin-desktop';
           'google-chrome'='chrome'; 'msedge'='edge'; 'browser'='edge' }
if ($alias.ContainsKey($appKey)) { $appKey = $alias[$appKey] }
$safeApp = ($appKey -replace '[^A-Za-z0-9._-]', '_').Trim('._-'); if (-not $safeApp) { $safeApp = 'default' }
$dataDir = Join-Path (Join-Path $Root $safeClone) $safeApp
New-Item -ItemType Directory -Force $dataDir | Out-Null

# 软件注册表：exe 候选 + 由 dataDir 派生的隔离参数/环境（与 Python 注册表一致）。
$reg = @{
  'vscode' = @{ exe=@("$env:ProgramFiles\Microsoft VS Code\Code.exe","$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe");
                args=@("--user-data-dir=$dataDir\data","--extensions-dir=$dataDir\ext"); env=@{} }
  'devin-desktop' = @{ exe=@("$env:LOCALAPPDATA\Programs\Devin\Devin.exe","$env:LOCALAPPDATA\Programs\Windsurf\Windsurf.exe","$env:ProgramFiles\Devin\Devin.exe","$env:ProgramFiles\Windsurf\Windsurf.exe");
                args=@("--user-data-dir=$dataDir\data","--extensions-dir=$dataDir\ext"); env=@{} }
  'chrome' = @{ exe=@("$env:ProgramFiles\Google\Chrome\Application\chrome.exe","${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe");
                args=@("--user-data-dir=$dataDir\data"); env=@{} }
  'edge' = @{ exe=@("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe","$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe");
                args=@("--user-data-dir=$dataDir\data"); env=@{} }
  'freecad' = @{ exe=@("$env:ProgramFiles\FreeCAD 1.0\bin\FreeCAD.exe","$env:LOCALAPPDATA\Programs\FreeCAD 1.0\bin\FreeCAD.exe");
                args=@(); env=@{ 'FREECAD_USER_HOME'="$dataDir\home" } }
}
if (-not $reg.ContainsKey($appKey)) {
  Write-Error "未登记隔离策略的软件: $App（可用: $($reg.Keys -join ', ')）。裸启动无法保证 per-user 单实例软件的分身隔离。"
  exit 2
}
$spec = $reg[$appKey]
$exe = $spec.exe | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $exe) { Write-Error "$appKey 可执行文件未找到，候选: $($spec.exe -join '; ')"; exit 3 }

foreach ($k in $spec.env.Keys) { Set-Item -Path "Env:$k" -Value $spec.env[$k] }
$argList = @($spec.args) + @($ExtraArgs)
Write-Host "[dao-clone-open] clone=$safeClone app=$appKey exe=$exe dataDir=$dataDir"
$p = Start-Process -FilePath $exe -ArgumentList $argList -PassThru
Write-Host "[dao-clone-open] launched pid=$($p.Id) session=$((Get-Process -Id $PID).SessionId)"
