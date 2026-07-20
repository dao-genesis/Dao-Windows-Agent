# 拉取浏览器端渲染/键位资产(mstsc.js·GPLv3·不入库,仅运行期取得)。
# 这些文件负责 RDP bitmap 的 RLE 解压(rle.js·emscripten)与扫描码映射(keyboard.js),
# 由官方 RDP 协议画面在 canvas 落地。gateway.js/client_ws.js/grid.html 为本仓原创,仅编排复用。
param([string]$Dir = (Join-Path $PSScriptRoot 'client'))
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$base = 'https://raw.githubusercontent.com/citronneur/mstsc.js/master/client/js'
foreach ($f in 'rle.js', 'keyboard.js', 'mstsc.js', 'canvas.js') {
  Invoke-WebRequest -Uri "$base/$f" -OutFile (Join-Path $Dir $f) -UseBasicParsing -TimeoutSec 60
  Write-Host ("fetched {0} -> {1} bytes" -f $f, (Get-Item (Join-Path $Dir $f)).Length)
}
Write-Host 'done'
