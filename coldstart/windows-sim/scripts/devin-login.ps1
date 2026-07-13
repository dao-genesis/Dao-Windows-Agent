# ☯ 冷启动·guest 内无头登录注入（彻底规避 GUI · rt-flow 本源移植）
#
# 道法自然：guest 内零键鼠完成 Devin 登录。两段式（账密永不落 guest·永不进 ISO/命令行）：
#   段一（宿主·可选）：宿主经环境变量跑 devin_login.sh 换 auth1 → 得 auth 束（仅 bearer 无密码）。
#   段二（本脚本·guest）：拿 auth 束（经 bridge 于运行时投递到 C:\dao_win\devin_auth.json）
#     → 以远程调试口拉起浏览器/Devin Desktop → 经 CDP 于 app.devin.ai 真源注入 auth1_session → 秒登。
#
# 用法（guest 内）：
#   powershell -File C:\dao_win\coldstart-auth\devin-login.ps1 -AuthJson C:\dao_win\devin_auth.json
#   [-Target devin|browser] [-DebugPort 9222]
#
# 诚实边界（见 AGENTS.md）：auth1_session 注入登录的是 Devin **网页/webview**（全功能可用）；
#   Devin Desktop 原生 welcome-gate 仍需官方 first-party session，本脚本不伪造、不绕过。

param(
  [string]$AuthJson = "C:\dao_win\devin_auth.json",
  [ValidateSet('devin','browser')][string]$Target = 'browser',
  [int]$DebugPort = 9222,
  [string]$Webapp = 'https://app.devin.ai'
)
$ErrorActionPreference = 'SilentlyContinue'
$log = "$env:SystemDrive\dao-devin-login.log"
function Log($m) { "$([DateTime]::Now.ToString('s')) $m" | Tee-Object -FilePath $log -Append }

if (-not (Test-Path $AuthJson)) { Log "auth 束缺失: $AuthJson（应由宿主经 bridge 于运行时投递·仅含 bearer）"; exit 2 }

# 解析 node：优先独立 node.exe；否则用 Electron 宿主（Code.exe/Devin.exe）+ ELECTRON_RUN_AS_NODE=1
# （Electron 应用不带独立 node.exe，但其主 exe 置 ELECTRON_RUN_AS_NODE=1 即为纯 node 运行时）。
function Resolve-Node {
  $c = Get-Command node.exe -ErrorAction SilentlyContinue
  if ($c) { return @{ exe = $c.Source; electron = $false } }
  foreach ($p in @(
    "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe",
    "$env:ProgramFiles\Microsoft VS Code\Code.exe",
    "$env:LOCALAPPDATA\Programs\Devin\Devin.exe")) {
    if (Test-Path $p) { return @{ exe = $p; electron = $true } }
  }
  return $null
}

# 解析可带远程调试口启动的浏览器/Devin Desktop。
function Resolve-Chromium($target) {
  if ($target -eq 'devin') {
    foreach ($p in @(
      "$env:LOCALAPPDATA\Programs\Devin\Devin.exe",
      "$env:LOCALAPPDATA\Programs\Windsurf\Windsurf.exe",
      "$env:LOCALAPPDATA\Programs\Devin\devin-desktop.exe")) {
      if (Test-Path $p) { return $p }
    }
  }
  foreach ($p in @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe")) {
    if (Test-Path $p) { return $p }
  }
  return $null
}

$node = Resolve-Node
if (-not $node) { Log "未找到 node/Electron 宿主（Devin Desktop/VSCode 未装？）—无法注入"; exit 3 }
$exe = Resolve-Chromium $Target
if (-not $exe) { Log "未找到可用浏览器/Devin Desktop（target=$Target）"; exit 4 }

$profile = "$env:TEMP\dao-devin-login-profile"
New-Item -ItemType Directory -Force $profile | Out-Null
Log "拉起 $exe --remote-debugging-port=$DebugPort（GUI-free 注入用）"
$args = @("--remote-debugging-port=$DebugPort", "--user-data-dir=$profile", "--no-first-run", "--no-default-browser-check", "$Webapp/login")
$proc = Start-Process -FilePath $exe -ArgumentList $args -PassThru
Start-Sleep -Seconds 6

$inject = Join-Path $PSScriptRoot 'devin_inject_cdp.js'
Log "CDP 注入登录态 …（runtime=$($node.exe) electron=$($node.electron)）"
if ($node.electron) { $env:ELECTRON_RUN_AS_NODE = '1' }
& $node.exe $inject $AuthJson "127.0.0.1:$DebugPort" $Webapp 2>&1 | Tee-Object -FilePath $log -Append
$rc = $LASTEXITCODE
if ($rc -eq 0) { Log "== 无头登录注入成功（零 GUI）==" } else { Log "注入返回码 $rc" }
exit $rc
