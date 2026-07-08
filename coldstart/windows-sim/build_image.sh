#!/usr/bin/env bash
# 无人值守构建 Windows 磁盘镜像：注入 autounattend.xml（跳过 OOBE、建本地管理员、
# 开 RDP、装 virtio + QEMU guest agent），产出可复现的 qcow2。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MEDIA="$HERE/media"; IMAGES="$HERE/images"; UNATTEND="$HERE/autounattend"
mkdir -p "$IMAGES"

edition="win11"; name="winlab"; size="64G"; ram="4096"; cpus="2"
while [ $# -gt 0 ]; do case "$1" in
  --edition) edition="$2"; shift 2;;
  --name) name="$2"; shift 2;;
  --size) size="$2"; shift 2;;
  --ram) ram="$2"; shift 2;;
  --cpus) cpus="$2"; shift 2;;
  *) echo "未知参数: $1"; exit 1;;
esac; done

ISO="$MEDIA/${edition}.iso"
[ -f "$ISO" ] || { echo "缺少安装 ISO: $ISO — 先跑 fetch_media.sh 或放入自带 ISO"; exit 1; }
UNATTEND_XML="$UNATTEND/${edition}.xml"
[ -f "$UNATTEND_XML" ] || UNATTEND_XML="$UNATTEND/default.xml"
[ -f "$UNATTEND_XML" ] || { echo "缺少 autounattend 模板: $UNATTEND_XML"; exit 1; }

DISK="$IMAGES/${name}.qcow2"
echo "== 创建磁盘 $DISK ($size) =="
qemu-img create -f qcow2 "$DISK" "$size" >/dev/null

# 把 autounattend.xml 打成一张小 ISO（Windows 安装器自动读取根目录 autounattend.xml）。
# 同时把机控桥（bridge/ + core/·纯 stdlib）随盘带入 guest，供 firstlogon 落地自启。
AUTO_ISO="$IMAGES/${name}-unattend.iso"
tmp="$(mktemp -d)"; cp "$UNATTEND_XML" "$tmp/autounattend.xml"
cp "$HERE/scripts/firstlogon.ps1" "$tmp/firstlogon.ps1" 2>/dev/null || true
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
for pkg in bridge core; do
  if [ -d "$REPO_ROOT/$pkg" ]; then
    rsync -a --exclude '__pycache__' "$REPO_ROOT/$pkg" "$tmp/" 2>/dev/null \
      || cp -r "$REPO_ROOT/$pkg" "$tmp/$pkg"
    find "$tmp/$pkg" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  fi
done
# IDE 前端 .vsix 一并带入（firstlogon 装 VSCode 后离线安装；缺则现打，打不出不阻断）
VSIX="$(ls "$REPO_ROOT"/ide/vscode/dao-windows-agent-*.vsix 2>/dev/null | head -1 || true)"
if [ -z "$VSIX" ] && command -v node >/dev/null 2>&1; then
  bash "$REPO_ROOT/ide/vscode/build.sh" >/dev/null 2>&1 || true
  VSIX="$(ls "$REPO_ROOT"/ide/vscode/dao-windows-agent-*.vsix 2>/dev/null | head -1 || true)"
fi
[ -n "$VSIX" ] && cp "$VSIX" "$tmp/" && echo "已捆入 IDE 插件: $(basename "$VSIX")"
genisoimage -quiet -J -r -o "$AUTO_ISO" "$tmp"; rm -rf "$tmp"

cat <<EOF
镜像准备完成：
  磁盘:        $DISK
  安装 ISO:    $ISO
  应答 ISO:    $AUTO_ISO
  virtio:      $MEDIA/virtio-win.iso
下一步：安装阶段启动（挂三张盘），装完 autounattend 自动关机；随后用 run_vm.sh 常态启动。
  bash "$HERE/run_vm.sh" --name "$name" --install --ram $ram --cpus $cpus
EOF
