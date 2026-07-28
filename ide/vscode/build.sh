#!/usr/bin/env bash
# ☯ 归一本源构建 — 本仓不自建插件前端, 唯一交付 = dao-one(devin-remote 真源) + 🪟 Windows 板块注入:
#   ① 取 devin-remote 真源(DAO_UPSTREAM 指向本地检出, 否则浅克隆到 .upstream/) 并构建 core/dao-one;
#   ② 经 dao-one-windows/inject.js 把 🪟 Windows 板块(官方 mstsc 五页/账号池/同源桌面路由)折入其全能板;
#   ③ pack_vsix.py 打成 dao-one-windows-<版本>.vsix。
# 隔离只在安装态: 与 Devin Desktop 内在研 dao-one 分宿主并存(鸡犬相闻·互不干扰), 底层同一, 绝非新架构。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

UPSTREAM="${DAO_UPSTREAM:-$HERE/.upstream/devin-remote}"
UPSTREAM_URL="${DAO_UPSTREAM_URL:-https://github.com/dao-genesis/devin-remote.git}"

echo "== ① dao-one 真源（devin-remote）=="
if [ ! -e "$UPSTREAM/core/dao-one/build.js" ]; then
  rm -rf "$UPSTREAM"
  git clone --depth 1 "$UPSTREAM_URL" "$UPSTREAM"
elif [ -d "$UPSTREAM/.git" ] && [ "${DAO_UPSTREAM_PULL:-1}" != "0" ]; then
  git -C "$UPSTREAM" pull --ff-only || echo "上游 pull 失败, 用现有检出继续"
fi

echo "== ② 构建 dao-one（真源 build.js 装配 vendor-*）=="
( cd "$UPSTREAM/core/dao-one" && npm install --no-audit --no-fund && node build.js )

echo "== ③ 注入 🪟 Windows 板块（dao-one-windows 衍生）=="
STAGE="$HERE/.stage/dao-one-win"
rm -rf "$STAGE"
node "$HERE/dao-one-windows/inject.js" "$UPSTREAM/core/dao-one" "$STAGE"

echo "== ④ 收敛为运行时形态（剔除构建器/开发依赖, 只留 ws 运行时依赖）=="
( cd "$STAGE" \
  && rm -rf node_modules build.js gen-manifest.js apply-overlay.js proxy-fold.patch package-lock.json .gitignore \
  && npm install --omit=dev --no-audit --no-fund )

echo "== ⑤ 打包 VSIX =="
VER="$(node -p "require('$STAGE/package.json').version")"
OUT="$HERE/dao-one-windows-${VER}.vsix"
python3 "$HERE/dao-one-windows/pack_vsix.py" "$STAGE" "$OUT"
echo "== 完成：$OUT =="
