# ☯ 交接文档 · 真机 live 推进现状（给下一个 Agent）

> 读本文前先读 `AGENTS.md`（本源认知）。本文只记录**跑到哪了、环境值、踩坑、下一步**，
> 供下一个 Agent 无缝接手，不重复架构叙述。

## 一、总进度（PR#1–10 全部已合入 main）

| 阶段 | 内容 | 状态 |
|---|---|---|
| PR#1–2 | 架构骨架 + bridge REST/MCP + CI 自动化 | ✅ |
| PR#3–4 | Win11 无人值守安装全链路（QEMU/KVM·26100）+ 验证归档 | ✅ |
| PR#5 | VM 内机控桥端到端 + 冷启动自动化（firstlogon 落桥） | ✅ |
| PR#6 | 级别① KiCad/FreeCAD profiles 深化 | ✅ |
| PR#7 | 级别② 隔离桌面 UIA 框架 + notepad 标靶 | ✅ |
| PR#8 | 级别② pywinauto driver + bridge 自动绑定 + coldstart 装依赖 | ✅ |
| PR#9 | 级别③ 视觉 grounding 适配器 + mspaint 标靶 | ✅ |
| PR#10 | 动词检索纯中文查询（CJK 单字+二元词元化） | ✅ |
| PR#11 | 桥改 SYSTEM+开机任务（抗 RDP 注销）+ 本交接文档 | ✅ |
| PR#12 | **真·隔离桌面基石 `win_desktop.py`**（CreateProcessW+SetThreadDesktop），修复级别② 隔离完全落空的致命 bug | ⬅️ |

离线自检：`python3 -m pytest tests -q` → **21 passed**（级别①②③ 全部 dry-run 可测，Linux 即可）。

### PR#12 的本源修复（务必理解，别退回老路）

1. 老 `uia_win.py` 用 `subprocess.STARTUPINFO().lpDesktop = desk` 起进程 —— **Python 的
   `subprocess.STARTUPINFO` 根本没有 `lpDesktop` 字段**，赋值被静默忽略，进程照样落在
   用户可见默认桌面，"单账号类多 RDP 隔离"完全落空。唯一正解：`CreateProcessW` +
   `STARTUPINFOW.lpDesktop`（见 `core/adapter/win_desktop.py::launch_on_desktop`）。
2. 驱动线程必须 `SetThreadDesktop(hdesk)` 绑到目标隔离桌面，否则 pywinauto/UIA 只枚举
   默认桌面，隔离桌面上的窗口根本找不到（见 `win_desktop.attached()` 上下文管理器）。
3. 独立桌面对象(HDESK)各有自己的输入/焦点上下文 → 隔离桌面上的操作天然不打扰用户
   可见桌面，这就是不建账号、不装 RDPWrap、零配置达到多 RDP 会话隔离效果的技术真身。

## 二、真机 live 验证跑到哪了（宿主 Linux VM 上的 QEMU Win11 guest）

**已达成：**
- guest 已跑最新 main 代码：`/api/health` 返回 5 apps（kicad/freecad/jlceda/notepad/mspaint）。
- pywinauto 已装入 guest（pip 到 user-site 成功）。
- 会话链路通：`session.create → open_app(notepad) → invoke(open/type_text/read_text)`
  全部 200，返回结构化 plan。

**卡点（下一步的第一件事）：**
- 级别② 仍是 dry-run：guest 内 `import pywinauto` 抛
  `ImportError: DLL load failed while importing win32ui / pywintypes`。
  根因：pywin32 装在 **user-site**（`%APPDATA%\Python\Python312\site-packages`），其 DLL
  未拷到 System32/未注册；`pywin32_postinstall`（user-site 的 exe 版）跑了仍失败。
- **修法（已走到一半）**：以管理员 PowerShell 全局重装：
  `pip uninstall -y pywinauto pywin32 comtypes; pip install pywinauto`（装到
  `C:\Program Files\Python312\Lib\site-packages`，DLL 随 all-users 安装正确落位）。
  已弹出 UAC 并按了 Yes（管理员窗口已开）；会话因宿主重启中断，**该命令需重跑**。
  验证：`& $py -c "import pywinauto; print(11111)"` 通过后重启桥，invoke 应不再带
  `dry_run:true` 而是真实 UIA 执行。

## 三、环境值（宿主 = 本 Devin VM）

- 仓库：`/home/ubuntu/repos/Dao-Windows-Agent`
- VM 启动：`coldstart/windows-sim/run_vm.sh`（镜像在 `coldstart/windows-sim/images/`）
- 端口转发：RDP `127.0.0.1:13389→3389`；桥 `127.0.0.1:19920→9920`；QMP `127.0.0.1:4444`；VNC `:0`
- guest 账号：`dao / Dao@2026!`（本地管理员）；桥 token：`dao-win-lab`
- 桥探活：`curl http://127.0.0.1:19920/api/health`
- guest 代码目录：`C:\dao_win`（bridge/ + core/）；Python：`C:\Program Files\Python312\python.exe`

## 四、真机操作的踩坑与正解（本轮实证）

1. **guest 访问 github.com 全挂**（iwr WebException，TLS1.2 也不行），但 pypi 可达。
   **正解**：宿主起 `python3 -m http.server 8888`，guest 用 `iwr http://10.0.2.2:8888/payload.zip`
   （slirp 网关 10.0.2.2 = 宿主）。payload 由宿主 `zip -r payload.zip bridge core` 现打。
2. **驱动 guest 的最稳通道**：宿主 `xfreerdp /v:127.0.0.1:13389` 开 RDP 窗口，
   `xdotool type --file <脚本> + key Return` 往 PowerShell 里灌一行式命令；截屏
   `import -window <wid>` 回读结果。UAC 弹窗用 `xdotool key alt+y` 点 Yes。
3. **旧桥任务 AtLogon+Interactive 随 RDP 注销即死**（曾连带拖死 QEMU）。本 PR 已把
   firstlogon.ps1 改为 **SYSTEM + AtStartup + 自动重启(999 次/1min)**，冷启动重建后生效；
   对**现存 guest** 需手工重注册一次（管理员 PS 里跑 firstlogon 的第 4 节等效命令）。
4. pip user-site 的 pywin32 DLL 必坏（见二·卡点）；**冷启动脚本 pip install 建议加 `--no-user`
   或以管理员跑**，下个 Agent 可顺手在 firstlogon.ps1 补上。

## 五、下一步（按优先级）

1. **验证 PR#12 隔离真身（真机）**：冷启动重建 guest 后，同一账号内并行开 N 个隔离桌面
   （`win_desktop.ensure_desktop("dao_vm1_notepad")` / `..._vm2_...`），各起一份 notepad，
   证明「N 窗口 = N 互不干扰实例、都不出现在用户可见默认桌面」。
2. 修 pywinauto DLL（二·卡点）：firstlogon 已带 `--no-user` 全局装；冷启动重建即应正常
   import。验证级别② round-trip：notepad `type_text("…") → read_text` 读回一致（无 `dry_run`）。
3. 级别③ 真机取证：mspaint `open → observe`（截图落盘）；grounder 仍是注入契约，
   接视觉模型属后续工程。
4. 长线：IddCx 虚拟显示器（级别② GPU 软件离屏）、vsix 插件端收编（参照 devin-remote）。

*道法自然 · 无为而无不为*
