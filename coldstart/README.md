# 冷启动 · 在 Linux VM 上模拟 Windows 环境（QEMU/KVM）

> 目标：让**我（Devin）或任意同环境 Agent** 无需用户本地设备，即可在自己的 Linux VM 上
> 拉起一套 Windows 10/11（家庭版/教育版/企业版通用）环境，用于开发、验证级别②/③（隔离桌面、
> 虚拟显示器、UIA、视觉）与端到端演化。级别① 无头（KiCad/FreeCAD/嘉立创）在纯 Linux 即可跑通，
> 不依赖本目录。

## 为什么用 QEMU/KVM（而非 Wine/容器）
- **Wine**：能跑部分 Windows 程序，但**不是真 Windows 内核**——UIA/桌面对象/`CreateDesktop`/
  虚拟显示器/RDP 会话等本体系要验证的 Windows 特性无法真实复现。仅作个别 exe 快速试跑的旁路。
- **Windows 容器**：无 GUI，无法验证桌面隔离与渲染。
- **QEMU/KVM**：真 Windows 内核 + 硬件加速（本 VM `/dev/kvm` 在、4×vmx），可跑任意版本 Win10/11，
  是验证"IDE 窗口=类虚拟机隔离会话"底层机制的唯一忠实途径。

## 环境自检
```bash
bash coldstart/windows-sim/preflight.sh
```
检查 `/dev/kvm`、CPU 虚拟化标志、内存/磁盘、qemu 是否就绪，并给出安装建议。

## 一键落地（幂等）
```bash
# 1) 装 qemu + 依赖（apt）
bash coldstart/windows-sim/install_qemu.sh

# 2) 取 Windows 介质（二选一）
#    a. 官方评估版 ISO（企业版，180 天，无需密钥，最适合可复现自动化）
#    b. 用户自带 ISO（家庭/教育/企业任意版本，放入 coldstart/windows-sim/media/）
bash coldstart/windows-sim/fetch_media.sh --eval win11

# 3) 无人值守安装（autounattend.xml 注入：跳过 OOBE、建本地管理员、开 RDP、装 QEMU guest agent）
bash coldstart/windows-sim/build_image.sh --edition win11 --name winlab

# 3.5) 安装阶段启动（三张光盘：安装/应答/virtio；CD 首启按键窗口已自动应答；装完自动关机）
bash coldstart/windows-sim/run_vm.sh --name winlab --install

# 4) 常态启动（headless + VNC/QMP，供 Agent 无头接入）
bash coldstart/windows-sim/run_vm.sh --name winlab
```

## ✅ 已实机验证（2026-07 · Devin VM · KVM 加速）

上述全链路已在 Devin 自己的 Linux VM 上端到端跑通，零人工：

- ISO：fwlink 直取 Win11 企业评估版（5.1GB ≈ 3 分钟）+ virtio-win
- 无人值守安装 ≈ 25 分钟到桌面（Build 26100 · 自动分区/跳 OOBE/建号/自动登录）
- RDP：`127.0.0.1:13389` 认证通过（`xfreerdp /u:dao /p:'Dao@2026!' +auth-only` exit 0）
- 观测：QMP `screendump`（4444 端口）随时截屏；VNC :0 可视
- 本地管理员：`dao / Dao@2026!`（见 autounattend/default.xml，仅限本地实验靶机）

## 通用版本适配（家庭/教育/企业 · Win10/Win11）
`autounattend/` 下按版本放模板；`build_image.sh --edition` 选择：
| edition | 说明 |
|---|---|
| `win11` / `win10` | 企业评估版（默认，可复现，无需密钥） |
| `win11-home` / `win11-edu` / `win11-pro` | 用户自带 ISO + 对应 `autounattend`（家庭版需绕过 MSA/联网 OOBE，模板已内置 `BypassNRO`） |

> 家庭版无组策略、RDP host 受限——正是本体系用**独立桌面对象/虚拟显示器**（而非 RDP）实现
> 隔离会话的价值所在：家庭版也能达到"IDE 窗口=类虚拟机"效果。

## 与本体系的衔接
Windows VM 起来后，把 `bridge/` 的机控守护进程（复用 devin-remote/vm-replica 骨架）装进去，
经 REST/MCP 暴露 `exec/file/screenshot/ui_tree/create_desktop/...`，即成为级别②/③ 适配器的落地靶机。
后续所有隔离桌面/虚拟显示器 PoC 都在此 VM 内进行，无需用户真机。
