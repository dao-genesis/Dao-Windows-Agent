#!/usr/bin/env bash
# 安装 QEMU/KVM 及依赖（Debian/Ubuntu apt）。幂等。
set -euo pipefail
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

if command -v qemu-system-x86_64 >/dev/null && command -v qemu-img >/dev/null; then
  echo "qemu 已就绪：$(qemu-system-x86_64 --version | head -1)"; exit 0
fi

echo "== 安装 qemu-kvm + 工具 =="
$SUDO apt-get update -y
$SUDO apt-get install -y --no-install-recommends \
  qemu-system-x86 qemu-utils ovmf swtpm swtpm-tools \
  genisoimage p7zip-full curl ca-certificates
# swtpm/OVMF: Win11 需要 UEFI + TPM 2.0；swtpm 提供软件 TPM。

# 尝试把当前用户加入 kvm 组（下次会话生效）
if [ "$(id -u)" -ne 0 ] && getent group kvm >/dev/null; then
  $SUDO usermod -aG kvm "$USER" || true
  echo "已尝试把 $USER 加入 kvm 组（重新登录后免 sudo 访问 /dev/kvm）"
fi
echo "完成：$(qemu-system-x86_64 --version | head -1)"
