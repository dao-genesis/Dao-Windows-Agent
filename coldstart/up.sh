#!/usr/bin/env bash
# ☯ 一键冷启动编排（幂等·断点续跑）—— 下一个 Agent 只需跑这一行即可从零到「IDE 即隔离会话」可用。
#
#   bash coldstart/up.sh                 # 全链路：装 qemu → 取介质 → 建镜像 → 装机(无人值守) → 常态启动
#   bash coldstart/up.sh --edition win10 # 指定版本
#   bash coldstart/up.sh --run-only      # 已装机，仅常态启动
#   bash coldstart/up.sh --status        # 只看现状（各阶段产物是否就绪 + 桥探活）
#
# 设计要点（针对"上两个对话冷启动太慢"的痛点）：
#   · 每阶段产物落盘即视为完成，重复跑自动跳过（ISO/镜像/装机哨兵），不重复下 5GB ISO、不重装机。
#   · 全程无人工：CD 首启按键、OOBE、建号、装 Python/桥/VSCode/插件 全部无人值守（autounattend+firstlogon）。
#   · 结束打印接入方式（RDP/桥/QMP/VNC），并把常态 VM 起在后台。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WSIM="$HERE/windows-sim"
MEDIA="$WSIM/media"; IMAGES="$WSIM/images"

edition="win11"; name="winlab"; ram="4096"; cpus="2"; mode="full"
while [ $# -gt 0 ]; do case "$1" in
  --edition) edition="$2"; shift 2;;
  --name) name="$2"; shift 2;;
  --ram) ram="$2"; shift 2;;
  --cpus) cpus="$2"; shift 2;;
  --run-only) mode="run"; shift;;
  --status) mode="status"; shift;;
  *) echo "未知参数: $1"; exit 1;;
esac; done

DISK="$IMAGES/${name}.qcow2"
INSTALLED_FLAG="$IMAGES/${name}.installed"

hr(){ echo "———————————————————————————————————————"; }
step(){ hr; echo "☯ $1"; hr; }

status(){
  echo "== 冷启动现状 (name=$name) =="
  [ -f "$MEDIA/${edition}.iso" ] && echo "  [OK]   安装 ISO: $MEDIA/${edition}.iso ($(du -h "$MEDIA/${edition}.iso"|cut -f1))" || echo "  [--]   安装 ISO 未就绪"
  [ -f "$MEDIA/virtio-win.iso" ] && echo "  [OK]   virtio-win.iso" || echo "  [--]   virtio-win.iso 未就绪"
  [ -f "$DISK" ] && echo "  [OK]   磁盘镜像: $DISK ($(du -h "$DISK"|cut -f1))" || echo "  [--]   磁盘镜像未建"
  [ -f "$INSTALLED_FLAG" ] && echo "  [OK]   已完成无人值守装机" || echo "  [--]   未完成装机"
  local h; h=$(curl -s -m3 http://127.0.0.1:19920/api/health -H 'Authorization: Bearer dao-win-lab' 2>/dev/null || true)
  [ -n "$h" ] && echo "  [OK]   桥探活: $h" || echo "  [--]   桥未响应 (127.0.0.1:19920)"
  pgrep -af "qemu-system-x86_64.*$name" >/dev/null && echo "  [OK]   VM 进程在跑" || echo "  [--]   VM 未运行"
  local gh; gh=$(curl -s -m3 "http://127.0.0.1:${DAO_GUAC_HTTP_PORT:-4824}/health" 2>/dev/null || true)
  [ -n "$gh" ] && echo "  [OK]   桌面路由隧道: $gh" || echo "  [--]   桌面路由隧道未响应 (guacd/tunnel · desktop/up_desktop.sh)"
}

run_vm_bg(){
  step "常态启动 VM（headless·后台）"
  if pgrep -af "qemu-system-x86_64.*$name" >/dev/null; then
    echo "VM 已在运行，跳过启动。"; return
  fi
  nohup bash "$WSIM/run_vm.sh" --name "$name" --ram "$ram" --cpus "$cpus" > "$IMAGES/${name}-run.log" 2>&1 &
  echo "VM 已后台启动 (log: $IMAGES/${name}-run.log)"
  echo "接入：RDP 127.0.0.1:13389 (dao/Dao@2026!) · 桥 127.0.0.1:19920 · QMP 127.0.0.1:4444 · VNC :0"
  echo "等待桥就绪（登录自启桥 + 插件激活会自动连桥）…"
  for i in $(seq 1 60); do
    h=$(curl -s -m3 http://127.0.0.1:19920/api/health -H 'Authorization: Bearer dao-win-lab' 2>/dev/null || true)
    if echo "$h" | grep -q '"ok"'; then echo "桥就绪 (${i}0s): $h"; return; fi
    sleep 10
  done
  echo "桥暂未就绪（guest 可能仍在登录/置备），可稍后 curl 探活或 --status 复查。"
}

case "$mode" in
  status) status; exit 0;;
  run) run_vm_bg; exit 0;;
esac

step "1/6 预检 + 安装 QEMU/KVM（幂等）"
bash "$WSIM/preflight.sh" || true
command -v qemu-system-x86_64 >/dev/null 2>&1 || bash "$WSIM/install_qemu.sh"

step "2/6 取 Windows 介质（评估版 ISO + virtio·已存在则跳过）"
if [ -f "$MEDIA/${edition}.iso" ] && [ -f "$MEDIA/virtio-win.iso" ]; then
  echo "介质已就绪，跳过下载。"
else
  bash "$WSIM/fetch_media.sh" --eval "$edition"
fi

step "3/6 构建镜像 + 应答盘（捆入 bridge/core + IDE 插件 vsix·已建则跳过)"
if [ -f "$DISK" ]; then
  echo "磁盘镜像已存在，跳过构建。删 $DISK 可强制重建。"
else
  bash "$WSIM/build_image.sh" --edition "$edition" --name "$name" --ram "$ram" --cpus "$cpus"
fi

step "4/6 无人值守装机（首次约 25 分钟·装完自动关机·已装则跳过）"
if [ -f "$INSTALLED_FLAG" ]; then
  echo "已完成装机（哨兵存在），跳过。删 $INSTALLED_FLAG 可强制重装。"
else
  echo "启动安装阶段（VNC:0 可观测；装完 autounattend 自动关机）…"
  # run_vm --install 前台阻塞至 guest 装完自动关机；仅 QEMU 正常退出(0)才算装机结束。
  # QEMU 崩溃（如 free(): invalid pointer）会以非零码退出——此时不落哨兵，自动重试。
  installed=0
  for attempt in 1 2 3; do
    if bash "$WSIM/run_vm.sh" --name "$name" --install --ram "$ram" --cpus "$cpus"; then
      installed=1; break
    fi
    echo "[WARN] 安装阶段 QEMU 非正常退出（第 $attempt 次）——重试续装（磁盘保留，装机可断点续行）…"
    sleep 3
  done
  [ "$installed" = "1" ] || { echo "[FATAL] 装机三次均异常退出，不落哨兵。查 VNC:0 或 qemu 版本（当前 $(qemu-system-x86_64 --version | head -1)）。"; exit 1; }
  # 装机真伪校验：SIGTERM 下 QEMU 也以 0 退出，磁盘实占过小即未真装完，不落哨兵。
  disk_bytes=$(stat -c %s "$DISK" 2>/dev/null || echo 0)
  [ "$disk_bytes" -ge $((5*1024*1024*1024)) ] || { echo "[FATAL] 装机退出但磁盘仅 $disk_bytes 字节（<5GB），判为未装完（如被信号终止），不落哨兵。"; exit 1; }
  touch "$INSTALLED_FLAG"
  echo "装机结束，落哨兵 $INSTALLED_FLAG"
fi

step "5/6 常态启动 + 等桥就绪"
run_vm_bg

step "6/6 桌面级路由链路（guacd + WS 隧道 · 路线A · 幂等）"
if bash "$HERE/../desktop/up_desktop.sh"; then
  echo "桌面路由链路就绪：guacd ${DAO_GUACD_PORT:-4822} · WS ${DAO_GUAC_WS_PORT:-4823} · 令牌 ${DAO_GUAC_HTTP_PORT:-4824}（RDP 目标 127.0.0.1:13389）"
else
  echo "[WARN] 桌面路由链路未拉起（Docker/Node 缺失？）——面板可开但连接不通；可稍后手动 bash desktop/up_desktop.sh"
fi

hr; echo "☯ 冷启动完成。IDE 即隔离会话：打开 guest 内 VSCode（插件已随盘装好）→ 状态栏 DAO 面板即为本窗口会话。"; hr
