#!/usr/bin/env bash
# 启动 Windows VM。--install 挂安装/应答/virtio 三盘跑无人值守安装；否则常态启动。
# 常态启动：headless + VNC(:0)+QMP，供 Agent 无头接入（后续机控桥经 RDP/HTTP 落地）。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MEDIA="$HERE/media"; IMAGES="$HERE/images"

name="winlab"; ram="4096"; cpus="2"; install=0; vnc="0"
while [ $# -gt 0 ]; do case "$1" in
  --name) name="$2"; shift 2;;
  --ram) ram="$2"; shift 2;;
  --cpus) cpus="$2"; shift 2;;
  --install) install=1; shift;;
  --vnc) vnc="$2"; shift 2;;
  *) echo "未知参数: $1"; exit 1;;
esac; done

DISK="$IMAGES/${name}.qcow2"
[ -f "$DISK" ] || { echo "磁盘不存在: $DISK — 先跑 build_image.sh"; exit 1; }

ACCEL="tcg"; [ -r /dev/kvm ] && [ -w /dev/kvm ] && ACCEL="kvm"
[ "$ACCEL" = "tcg" ] && echo "[WARN] 无 KVM 权限，回退 tcg 软件模拟(慢)。"

# UEFI + TPM2（Win11 必需）
OVMF_CODE="/usr/share/OVMF/OVMF_CODE_4M.fd"; [ -f "$OVMF_CODE" ] || OVMF_CODE="/usr/share/OVMF/OVMF_CODE.fd"
VARS="$IMAGES/${name}_VARS.fd"
[ -f "$VARS" ] || cp "$(dirname "$OVMF_CODE")/OVMF_VARS_4M.fd" "$VARS" 2>/dev/null || cp /usr/share/OVMF/OVMF_VARS.fd "$VARS" 2>/dev/null || true
TPMDIR="$IMAGES/${name}-tpm"; mkdir -p "$TPMDIR"
if command -v swtpm >/dev/null; then
  swtpm socket --tpmstate dir="$TPMDIR" --ctrl type=unixio,path="$TPMDIR/swtpm-sock" --tpm2 --daemon 2>/dev/null || true
  TPM_ARGS=(-chardev socket,id=chrtpm,path="$TPMDIR/swtpm-sock" -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0)
else
  TPM_ARGS=(); echo "[WARN] 无 swtpm，Win11 TPM 检查可能失败(可用 win10 或注册表绕过)。"
fi

args=(qemu-system-x86_64 -name "$name" -machine q35,accel=$ACCEL -cpu host -smp "$cpus" -m "$ram"
  -drive if=pflash,format=raw,unit=0,readonly=on,file="$OVMF_CODE"
  -drive if=pflash,format=raw,unit=1,file="$VARS"
  "${TPM_ARGS[@]}"
  -device e1000,netdev=n0 -netdev user,id=n0,hostfwd=tcp::13389-:3389,hostfwd=tcp::19920-:9920
  -drive file="$DISK",if=ide,format=qcow2,cache=writeback
  -vga std -display vnc=:$vnc -qmp tcp:127.0.0.1:4444,server,nowait
  -device virtio-serial -chardev socket,path="$IMAGES/${name}-qga.sock",server=on,wait=off,id=qga0
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0)

if [ "$install" = "1" ]; then
  ISO_INSTALL="$MEDIA/$(ls "$MEDIA" | grep -E '^win(10|11).*\.iso$' | head -1)"
  args+=(-drive file="$ISO_INSTALL",media=cdrom
    -drive file="$IMAGES/${name}-unattend.iso",media=cdrom
    -drive file="$MEDIA/virtio-win.iso",media=cdrom
    -boot d)
  echo "== 无人值守安装启动（VNC :$vnc）：安装完成后自动关机 =="
  # UEFI CD 首启有「Press any key」窗口：后台经 QMP 连发回车 30s，免人工。
  ( sleep 3; python3 - <<'PYEOF'
import socket, json, time
for _ in range(30):
    try:
        s = socket.create_connection(("127.0.0.1", 4444), timeout=2); break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit
s.recv(4096)
s.sendall(b'{"execute":"qmp_capabilities"}\n'); s.recv(4096)
for _ in range(60):
    s.sendall(json.dumps({"execute": "send-key", "arguments": {"keys": [{"type": "qcode", "data": "ret"}]}}).encode() + b"\n")
    try: s.recv(4096)
    except OSError: break
    time.sleep(0.5)
PYEOF
  ) &
fi

echo "转发: RDP 127.0.0.1:13389 → guest:3389 ; 机控桥 127.0.0.1:19920 → guest:9920 ; VNC :$vnc ; QMP 127.0.0.1:4444"
exec "${args[@]}"
