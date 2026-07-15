#!/usr/bin/env bash
# ☯ 桌面级路由 · 一键拉起全链路（路线A）
#
#   bash desktop/up_desktop.sh
#
# 依次确保：
#   1. guacd（Docker 容器，RDP→guac 协议代理，默认 4822）
#   2. WebSocket 隧道（Node，浏览器 WS ↔ guacd，默认 WS 4823 + 令牌 HTTP 4824）
# 幂等：已跑的组件自动跳过。VM 需已启动（coldstart/up.sh）。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

echo "☯ 桌面级路由 · 路线A 全链路启动"
echo "==================================="

# 1) guacd
bash "$HERE/guacd.sh"

# 2) WebSocket 隧道（后台常驻）
TUNNEL_PID=""
if pgrep -f "node.*desktop/tunnel/server.js" >/dev/null 2>&1; then
  TUNNEL_PID="$(pgrep -f 'node.*desktop/tunnel/server.js' | head -1)"
  echo "[tunnel] 已在运行 pid=$TUNNEL_PID"
else
  cd "$HERE/tunnel"
  [ -d node_modules ] || npm install --no-audit --no-fund
  # 以绝对路径启动，令 cmdline 含 desktop/tunnel/server.js——上方 pgrep 幂等判定才认得它；
  # 否则二次执行永远探不到已跑实例，重复起进程撞 EADDRINUSE。
  nohup node "$HERE/tunnel/server.js" > /tmp/dao-tunnel.log 2>&1 &
  TUNNEL_PID="$!"
  echo "[tunnel] 已启动 pid=$TUNNEL_PID → 日志 /tmp/dao-tunnel.log"
  sleep 1
  tail -3 /tmp/dao-tunnel.log 2>/dev/null || true
fi

echo ""
echo "==================================="
echo "☯ 路线A 就绪"
echo "  guacd:   127.0.0.1:${DAO_GUACD_PORT:-4822}"
echo "  隧道WS:  ws://127.0.0.1:${DAO_GUAC_WS_PORT:-4823}/?token=<token>"
echo "  令牌HTTP: http://127.0.0.1:${DAO_GUAC_HTTP_PORT:-4824}/token?ide=<hash>"
echo ""
echo "测试：curl -s http://127.0.0.1:${DAO_GUAC_HTTP_PORT:-4824}/health"
echo "  或在浏览器打开 file://$REPO/desktop/test.html 直连桌面"
echo "==================================="
