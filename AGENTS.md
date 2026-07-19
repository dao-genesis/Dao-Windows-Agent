# AGENTS.md · 本源认知（后续 Agent 必读）

> 道法自然 · 无为而无不为 · 反者道之动。改本仓前先读完本文，再读 [`README.md`](README.md)。

> **⚠️ 本源已于最新一轮正本清源修正——先读 [`docs/正本清源-桌面级路由本源.md`](docs/正本清源-桌面级路由本源.md)。**
> 本文以下第一节的旧表述（"不是投屏/绕过 GUI 直达自动化面"为主形态）**已被取代**：新本源是
> **把整台 Windows 的桌面本体（整块 GUI）以原生远程桌面协议级（类多 RDP）路由进 IDE 面板**，
> 面板内直接操作真实桌面。旧的桥 `/api/*` 与级别①②③ **降级为"控制面/自动化后端"**，不再是前端主形态。

## 一、本源（先记住 · 以正本清源文档为准）
1. **本仓 = 把整台 Windows 做进一个 IDE 插件，达到多实例类虚拟机效果。** 每个 IDE 窗口 =
   一路**独立完整的 Windows 桌面会话**（≈ 多 RDP 的一路），AI 与用户经 IDE 面板全权操作，
   与用户真实桌面**并行、互不干扰**。
2. **面板 = 整块 Windows 桌面本体**（走 RDP/RemoteApp 这类原生远程桌面协议送**真实会话**，
   canvas 渲染进 Webview）。**"不是投屏"= 不是像素截图推流**，而是原生桌面级会话路由——比投屏高级，
   非比投屏更"无 GUI"。所见即所得，直接鼠键操作。
3. **控制面（原级别①②③）降级为后端辅助**：Agent 需精确、可脚本化、无头操作时走桥 `/api/*`
   （exec/file/proc、profile 动词、UIA、PrintWindow）。它服务于桌面路由的编排/校验/批处理，非主前端。
4. **新增软件 = 写一个 profile（薄片），不改框架**（樸散則為器）——仍适用于控制面自动化加速层。

## 二、不要重造（复用既有成果）
- KiCad/嘉立创驱动在 **Dao-PCB-Design-Agent**；FreeCAD 在 **Dao-3D-Modeling-Agent**；
  agent 循环/帛书/工具发现在 **ha-copilot**；机控桥/类虚拟机骨架/调研成果已**迁入本仓 [`vm-replica/`](vm-replica/)**
  （原 devin-remote/cloud/vm-replica·正本清源后归位：devin-remote 只留归一插件本体，Windows Agent 延伸全在本仓）。
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
