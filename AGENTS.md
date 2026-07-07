# AGENTS.md · 本源认知（后续 Agent 必读）

> 道法自然 · 无为而无不为 · 反者道之动。改本仓前先读完本文，再读 [`README.md`](README.md)。

## 一、本源（先记住）
1. **本仓 = 把整台 Windows 做进一个 IDE 插件，达到多实例类虚拟机效果。** 每个 IDE 窗口 =
   一个隔离 session（类虚拟机），AI 全权操作用户电脑一切资源，与用户真实桌面**并行、互不干扰**。
2. **不是投屏。** 比投屏更底层——**绕过 GUI 直达每个软件自己的自动化面**（API/CLI/CDP）。
   投屏是被明确否定的低级形态。
3. **三级降级是铁律**：能走级别①（原生 API/CLI/CDP·无头）就绝不上级别②③（隔离桌面 UIA/视觉）。
   用户点名的 KiCad/嘉立创/FreeCAD **全在级别①**。
4. **新增软件 = 写一个 profile（薄片），不改框架**（樸散則為器）。框架只认 profile 声明的动词。

## 二、不要重造（复用既有成果）
- KiCad/嘉立创驱动在 **Dao-PCB-Design-Agent**；FreeCAD 在 **Dao-3D-Modeling-Agent**；
  agent 循环/帛书/工具发现在 **ha-copilot**；机控桥/类虚拟机骨架/调研在 **devin-remote/cloud/vm-replica**。
- 收编时把现有驱动函数包成 profile 的 verb handler，别从零写。

## 三、级别② 隔离的技术真相（做前必读，防走弯路）
- 单账号内"与用户可见桌面互不干扰的并行会话"：Win32 `CreateDesktop` 独立桌面 +
  **消息级输入**(PostMessage，不抢焦点) + PrintWindow 采集；**GPU 渲染软件**需 **虚拟显示器驱动**
  (IddCx) 离屏合成 + Desktop Duplication。对标 microsoft/UFO 的 Picture-in-Picture 桌面。
- **诚实边界**：必须真实输入队列+真 GPU 且无任何 API 的软件，单账号零配置隔离是 Windows 固有约束；
  级别② 虚拟显示器是当前最优解，极端情况才回退 RDP 会话（vm-replica 老路，用户要规避其配置负担）。

## 四、冷启动（我自己的 VM，不依赖用户真机）
- `coldstart/` 用 QEMU/KVM 在 Linux VM 上模拟 Win10/11（家庭/教育/企业通用），供级别②③ 与端到端演化。
- 级别① 纯 Linux 即可跑通，不需要冷启动 VM。
- **不要用 Wine/容器替代 QEMU** 去验证桌面隔离——它们不是真 Windows 内核，无法忠实复现 UIA/桌面对象/虚拟显示器。

## 五、自检
```bash
python3 -m pytest tests -q            # 核心单测（级别① 纯逻辑）
bash coldstart/windows-sim/preflight.sh   # 冷启动环境自检
```
