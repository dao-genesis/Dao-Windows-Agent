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

echo "== 二合一装配（可选：DAO_UNIFY_SRCS 给出领域插件目录列表，折入 vendor/ 并合并 contributes）=="
if [ -n "${DAO_UNIFY_SRCS:-}" ]; then
  # 例: DAO_UNIFY_SRCS="$HOME/repos/Dao-3D-Modeling-Agent/90-归一_IDE/vscode-dao-freecad $HOME/repos/Dao-PCB-Design-Agent/vscode-dao-kicad"
  # shellcheck disable=SC2086
  node "$HERE/unify.js" $DAO_UNIFY_SRCS
else
  echo "跳过（未设 DAO_UNIFY_SRCS；纯主体 + AI 基底打包）"
fi

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

echo "== webview 脚本编译自检（模板字面量转义陷阱：\\/ 会被吞成 /，node --check 直查源码测不出）=="
node - "$HERE/extension.js" <<'JS'
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
// 提取 desktopHtml 的模板字面量并按模板语义渲染（占位符以哑值代入），再编译内联 <script>。
const vscode = { Uri: { joinPath: () => ({}) } };
const sandbox = { require: (n) => n === 'vscode' ? vscode : require(n), module: { exports: {} }, exports: {}, console };
vm.runInContext(src + '\nglobalThis.__dh = desktopHtml;', vm.createContext(sandbox));
const html = sandbox.__dh({ asWebviewUri: () => 'x', cspSource: 'x' }, { extensionUri: {} },
  'ide_x', null, 'http://127.0.0.1:4824', 4823, [{ name: 'x' }]);
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('未找到内联脚本'); process.exit(1); }
try { new vm.Script(m[1]); console.log('webview 脚本编译通过'); }
catch (e) { console.error('webview 脚本编译失败:', e.message); process.exit(1); }
JS

echo "== vsce package =="
VER="$(node -p "require('$HERE/package.json').version" 2>/dev/null || echo 0.1.0)"
OUT="$HERE/dao-windows-agent-${VER}.vsix"
# --base*Url 必给：README 内有相对链接（../../docs/*），缺则 vsce 报错中断（真机踩坑）。
VSCE_ARGS=(package --no-dependencies --allow-missing-repository \
  --baseContentUrl https://example.invalid --baseImagesUrl https://example.invalid -o "$OUT")
if command -v vsce >/dev/null 2>&1; then
  vsce "${VSCE_ARGS[@]}"
else
  echo "vsce 未装：改用 npx @vscode/vsce"
  npx --yes @vscode/vsce "${VSCE_ARGS[@]}"
fi
echo "== 完成：$OUT =="
