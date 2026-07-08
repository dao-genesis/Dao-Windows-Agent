#!/usr/bin/env bash
# ☯ 桌面级路由 · 启动 guacd（Apache Guacamole RDP→guac 协议代理）
# 用法：bash desktop/guacd.sh [--port 4822] [--foreground]
# 幂等：已跑则跳过。guacd 是路线A 的核心——把 RDP 协议翻译为 Guacamole 指令流。
set -euo pipefail
PORT="${DAO_GUACD_PORT:-4822}"
NAME="dao-guacd"

# 已有同名容器且活着则跳过
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${NAME}$"; then
  echo "[guacd] 已在运行（$NAME 端口 $PORT）"
  exit 0
fi

# 有同名但停了 → 删掉重建
docker rm -f "$NAME" 2>/dev/null || true

echo "[guacd] 启动 guacamole/guacd:1.5.5 → 127.0.0.1:$PORT"
docker run -d --name "$NAME" \
  -p "127.0.0.1:${PORT}:4822" \
  --restart unless-stopped \
  guacamole/guacd:1.5.5

echo "[guacd] 就绪 127.0.0.1:$PORT"
