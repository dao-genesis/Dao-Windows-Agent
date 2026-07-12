#!/usr/bin/env bash
# ☯ 冷启动·无头登录编排（彻底规避 GUI · 本源移植自 devin-remote/rt-flow）
#
# 道法自然：账密只经环境变量传入(绝不落盘/绝不入日志/绝不进 ISO 或命令行历史)，
#   无头换 auth1 → 只把 auth 束(bearer·无密码)落 gitignored 文件 → 供 CDP 注入消费。
#
# 用法：
#   DEVIN_ACCOUNT_EMAIL=... DEVIN_ACCOUNT_PASSWORD=... \
#     bash devin_login.sh [auth_out.json] [cdp_host:port]
#
#   auth_out.json : auth 束落盘路径（默认 ~/.dao/devin_auth.json · 0600）
#   cdp_host:port : 给定则登录后立即经 CDP 于 app.devin.ai 真源注入登录态并验证
#
# 出参：stdout 仅打印脱敏摘要（userId/orgId/orgName），永不打印 auth1/密码。

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

AUTH_OUT="${1:-$HOME/.dao/devin_auth.json}"
CDP="${2:-}"

: "${DEVIN_ACCOUNT_EMAIL:?需设置环境变量 DEVIN_ACCOUNT_EMAIL}"
: "${DEVIN_ACCOUNT_PASSWORD:?需设置环境变量 DEVIN_ACCOUNT_PASSWORD（仅本会话内存·勿写盘）}"

command -v node >/dev/null 2>&1 || { echo "[ERR] 需要 node（Devin Desktop/VSCode 自带）"; exit 1; }

mkdir -p "$(dirname "$AUTH_OUT")"
chmod 700 "$(dirname "$AUTH_OUT")" 2>/dev/null || true

echo "☯ 无头登录 $DEVIN_ACCOUNT_EMAIL …（账密不落盘/不入日志）"
# 经 node 从环境读密码 → 换 auth1 → 落 auth 束（脚本不接触明文密码字符串）。
node -e '
const {login}=require(process.argv[1]);
const fs=require("fs");
(async()=>{
  const r=await login(process.env.DEVIN_ACCOUNT_EMAIL, process.env.DEVIN_ACCOUNT_PASSWORD);
  if(!r.ok){ process.stderr.write("[登录失败] "+r.error+"\n"); process.exit(1); }
  fs.writeFileSync(process.argv[2], JSON.stringify(r), {mode:0o600});
  process.stdout.write("[OK] user="+r.userId+" org="+r.orgId+" name="+(r.orgName||"-")+"\n");
})().catch(e=>{process.stderr.write("[ERR] "+(e&&e.message||e)+"\n");process.exit(1);});
' "$HERE/devin_auth.js" "$AUTH_OUT"

chmod 600 "$AUTH_OUT" 2>/dev/null || true
echo "[OK] auth 束 → $AUTH_OUT （已 gitignore · 0600 · 仅含 bearer 无密码）"

if [ -n "$CDP" ]; then
  echo "☯ 经 CDP($CDP) 于 app.devin.ai 真源注入登录态 …"
  node "$HERE/devin_inject_cdp.js" "$AUTH_OUT" "$CDP"
fi
