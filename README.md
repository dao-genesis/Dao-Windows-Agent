# Dao-Windows-Agent · 把整个 Windows 电脑做进 IDE 插件

> 反者道之动 · 无为而无不为 · 道法自然
>
> 目标：把用户整台 Windows 电脑做进一个 IDE 插件，达到**多实例类虚拟机**效果——
> 每个 IDE 窗口 = 一个隔离会话（类虚拟机实例），AI 在其中全权操作用户电脑一切资源
> （软件/文件/登录态/底层），与用户真实桌面**并行、互不干扰**；开 N 个窗口 = N 个隔离实例。
> **不是投屏**：比投屏更底层——绕过 GUI 直达每个软件自己的自动化面。

---

## 一句话架构

```
IDE 窗口 (webview) ── 每窗口一个 session_id (类虚拟机实例) ──┐
  对话 / agent 循环 (帛书提示词纪律，移植自 ha-copilot)       │
        │                                                    │
        ▼                                                    │
  插件后端守护进程 (bridge/，复用 devin-remote/vm-replica 骨架) │
        │  会话管理 create/open_app/invoke/destroy·端口路由    │
        ▼                                                    │
  通用应用适配层 (core/) ── App Profile 注册表 (热加载·软编码) ─┤
    ├─ 级别① API/CLI/CDP 无头(首选)：kicad · freecad · jlceda │
    ├─ 级别② 隔离桌面(CreateDesktop/虚拟显示器)+UIA           │
    └─ 级别③ 视觉 grounding 兜底                              │
        │  双层暴露：REST(内核) + MCP(外壳)                    │
        ▼                                                    │
  冷启动 (coldstart/) ── 我自己的 Linux VM 上 QEMU/KVM 模拟 ──┘
    Windows 10/11 (家庭/教育/企业通用)，无需用户本地设备
```

## 三级降级驱动（樸散則為器：新增软件 = 写一个 profile，不重造框架）

| 级别 | 手段 | 隔离性 | 适用 |
|---|---|---|---|
| **①（首选·覆盖 90% 价值）** | 软件原生 API / CLI / CDP（无头子进程或页面上下文） | **天然隔离·并行·不上可见桌面·零 RDP** | KiCad(kicad-cli/pcbnew)、FreeCAD(FreeCADCmd)、嘉立创EDA(CDP `_EXTAPI_ROOT_`)、任意可脚本软件 |
| **②** | Win32 `CreateDesktop` 独立桌面 / 虚拟显示器 + UIAutomation | 不占用户可见桌面·消息级输入不抢焦点 | 有 GUI 无 API 的软件 |
| **③** | 隔离桌面 + 视觉 grounding | 同② | 连 UIA 都无的软件 |

> 详见 [`docs/全链路架构分析.md`](docs/全链路架构分析.md)（五仓库解构 + 技术真相 + 推进次第）。

## 目录

| 路径 | 说明 |
|---|---|
| `core/` | 通用应用适配层：profile schema、adapter（subprocess_api/cdp）、session 管理、registry、agent 帛书 |
| `core/profiles/builtin/` | 内置画像：kicad / freecad / jlceda（收编自 Dao-PCB / Dao-3D 现有驱动） |
| `coldstart/` | Linux VM 上 QEMU/KVM 冷启动 Windows 模拟环境（Win10/11 通用，无人值守） |
| `bridge/` | 机控守护进程落地位（复用 devin-remote/vm-replica，REST+MCP 暴露） |
| `docs/` | 全链路架构分析 + `研究归档/`（vm-replica 调研：多RDP/GitHub项目/架构探讨） |
| `tests/` | 核心单测（级别① 纯逻辑，无需真机/GUI） |

## 快速开始（级别① · 纯 Linux，无需真机）

```bash
python3 -m pytest tests -q          # 核心单测
python3 - <<'PY'
from core.profiles.builtin import build_default_registry
from core.session.manager import SessionManager
reg = build_default_registry()
mgr = SessionManager(reg)
mgr.create("vm1"); mgr.open_app("vm1", "kicad")
print(reg.search_verbs("导出 gerber"))          # 跨软件动词检索
print(mgr.invoke("vm1", "kicad", "version").logs)  # 真机/装了 kicad-cli 即真跑
PY
```

## 冷启动 Windows 模拟（我自己的 VM，供后续演化）
```bash
bash coldstart/windows-sim/preflight.sh      # 自检 KVM/内存/磁盘/qemu
bash coldstart/windows-sim/install_qemu.sh   # 装 qemu-kvm + OVMF + swtpm
# 取介质(评估版或自带 ISO) → 无人值守构建 → 无头启动，详见 coldstart/README.md
```

## 收编来源（不重造·复用既有成果）
- **KiCad / 嘉立创EDA** ← Dao-PCB-Design-Agent（路线B pcb_brain/kicad_origin · 路线A lceda_bridge/cdp_studio）
- **FreeCAD** ← Dao-3D-Modeling-Agent（freecad_backend / _fc_remote_server :18920）
- **agent 循环 + 帛书 + 工具发现** ← ha-copilot（search_tools/describe_tool/run_tools 配方）
- **机控桥 + 类虚拟机会话骨架 + 调研** ← devin-remote/cloud/vm-replica + addons/dao-bridge

*道法自然 · 无为而无不为*
