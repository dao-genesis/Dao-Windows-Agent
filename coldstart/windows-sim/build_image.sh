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

# 把 autounattend.xml 打成一张小 ISO（Windows 安装器自动读取根目录 autounattend.xml）
AUTO_ISO="$IMAGES/${name}-unattend.iso"
tmp="$(mktemp -d)"; cp "$UNATTEND_XML" "$tmp/autounattend.xml"
cp "$HERE/scripts/firstlogon.ps1" "$tmp/firstlogon.ps1" 2>/dev/null || true
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
