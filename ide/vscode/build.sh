#!/usr/bin/env bash
# 打包 VSIX：把 bridge/ + core/（纯 stdlib）捆进 runtime/，再 vsce package。
# 这样插件自带一份可自启的机控桥，达成零配置冷启动（连不上外部桥就用自带 runtime 起本地桥）。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

echo "== 捆入 Python runtime（bridge/ + core/）=="
rm -rf "$HERE/runtime"
mkdir -p "$HERE/runtime"
cp -r "$REPO/bridge" "$HERE/runtime/bridge"
cp -r "$REPO/core" "$HERE/runtime/core"
find "$HERE/runtime" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "== 生成 PNG 图标（若缺）=="
if [ ! -f "$HERE/media/dao.png" ]; then
  python3 - "$HERE/media/dao.png" <<'PY' 2>/dev/null || echo "跳过图标生成（无 PIL）"
import sys
try:
    from PIL import Image, ImageDraw
    s=256; img=Image.new("RGBA",(s,s),(24,24,28,255)); d=ImageDraw.Draw(img)
    d.ellipse((28,28,s-28,s-28),outline=(240,240,240,255),width=6)
    d.text((s//2-8,s//2-16),"☯",fill=(240,240,240,255))
    img.save(sys.argv[1])
except Exception as e:
    raise SystemExit(1)
PY
fi

echo "== vsce package =="
if ! command -v vsce >/dev/null 2>&1; then
  echo "vsce 未装：npm i -g @vscode/vsce（或 npx @vscode/vsce package）"
  npx --yes @vscode/vsce package --no-dependencies --allow-missing-repository -o "$HERE/dao-windows-agent-0.1.0.vsix"
else
  vsce package --no-dependencies --allow-missing-repository -o "$HERE/dao-windows-agent-0.1.0.vsix"
fi
echo "== 完成：$HERE/dao-windows-agent-0.1.0.vsix =="
