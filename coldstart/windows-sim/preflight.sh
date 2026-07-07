#!/usr/bin/env bash
# 冷启动环境自检：确认本 Linux VM 能否承载 Windows QEMU/KVM 虚拟机。
set -uo pipefail

echo "== Dao-Windows-Agent · 冷启动自检 =="

ok=0; warn=0
say_ok(){ echo "  [OK]   $1"; }
say_warn(){ echo "  [WARN] $1"; warn=$((warn+1)); }

# CPU 虚拟化
vmx=$(grep -Ec '(vmx|svm)' /proc/cpuinfo || true)
if [ "$vmx" -gt 0 ]; then say_ok "CPU 虚拟化标志 x$vmx"; else say_warn "无 vmx/svm：只能纯软件模拟(极慢)"; fi

# KVM
if [ -e /dev/kvm ]; then
  if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then say_ok "/dev/kvm 可读写(硬件加速可用)"; else say_warn "/dev/kvm 存在但当前用户无权限(需加入 kvm 组或 sudo)"; fi
else
  say_warn "/dev/kvm 不存在：无 KVM 加速"
fi

# 内存/磁盘
mem=$(free -m | awk '/^Mem:/{print $2}')
[ "$mem" -ge 4096 ] && say_ok "内存 ${mem}MB" || say_warn "内存 ${mem}MB (<4G，Win11 建议 ≥4G)"
free_g=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[ "${free_g:-0}" -ge 40 ] && say_ok "磁盘可用 ${free_g}G" || say_warn "磁盘可用 ${free_g}G (<40G，Win 安装建议 ≥40G)"

# qemu
if command -v qemu-system-x86_64 >/dev/null; then say_ok "qemu-system-x86_64: $(qemu-system-x86_64 --version | head -1)"; else say_warn "qemu 未装 → 运行 coldstart/windows-sim/install_qemu.sh"; fi
command -v qemu-img >/dev/null && say_ok "qemu-img 就绪" || say_warn "qemu-img 未装"

echo
if [ "$warn" -eq 0 ]; then echo "结论：环境就绪，可直接 build_image.sh。"; else echo "结论：$warn 项需处理(见上)；多数可用 install_qemu.sh + sudo 解决。"; fi
