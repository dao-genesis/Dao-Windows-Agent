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
| PR#12 | **真·隔离桌面基石 `win_desktop.py`**（CreateProcessW+SetThreadDesktop），修复级别② 隔离完全落空的致命 bug | ✅ |
| PR#13 | **消息级本源 driver（纯 ctypes，弃 pywinauto/pywin32）+ 真机 live 全绿** | ⬅️ |

离线自检：`python3 -m pytest tests -q` → **22 passed**（级别①②③ 全部 dry-run 可测，Linux 即可）。

### PR#12/13 的本源修复（务必理解，别退回老路）

1. 老 `uia_win.py` 用 `subprocess.STARTUPINFO().lpDesktop = desk` 起进程 —— **Python 的
   `subprocess.STARTUPINFO` 根本没有 `lpDesktop` 字段**，赋值被静默忽略，进程照样落在
   用户可见默认桌面，"单账号类多 RDP 隔离"完全落空。唯一正解：`CreateProcessW` +
   `STARTUPINFOW.lpDesktop`（见 `core/adapter/win_desktop.py::launch_on_desktop`）。
2. **弃 pywinauto/pywin32（PR#13 本源之路）**：UIA `Desktop(backend='uia')` 无视
   `SetThreadDesktop` 绑定、够不着隔离桌面上的窗口（实测 descendants 返回 0）；且 pywin32
   DLL 注册地狱（user-site 装的 win32ui DLL 加载失败）违背"0 配置去中心化"。**改为纯
   ctypes 消息级 driver**：`_WinMsgDriver` 按 hwnd 直达窗口 —— `WM_SETTEXT`/`WM_GETTEXT`
   读写文本、`WM_CHAR` 敲字、`BM_CLICK`/`PostMessage` 点击、`PrintWindow`+DIB 跨桌面取图。
   与窗口在哪张桌面、是否输入桌面无关，且**不抢用户焦点** —— 这才是"类多 RDP 隔离"真身。
3. **`attached()` 改 best-effort**：本模块所有原语都按句柄直达（`EnumDesktopWindows` 走
   hdesk、launch 走 lpDesktop、输入/取图走 hwnd），**不依赖线程桌面绑定**。
   `SetThreadDesktop` 要求调用线程无窗口/hook，Python 主线程常因宿主已挂窗口而报
   `ERROR_BUSY(170)`；故"能绑则绑、绑不上不拦路"。桥每请求独立线程能绑上，主线程跑
   也照样工作。
4. 独立桌面对象(HDESK)各有自己的输入/焦点上下文 → 隔离桌面上的操作天然不打扰用户
   可见桌面，这就是不建账号、不装 RDPWrap、零配置达到多 RDP 会话隔离效果的技术真身。

## 二、真机 live 验证跑到哪了（宿主 Linux VM 上的 QEMU Win11 guest）

**本轮已全绿实证（真 QEMU Win11 guest，走真实 registry→profile→driver 全栈）：**

- `win_available=true`、`driver_available=true` —— **纯 ctypes driver 真执行，无 `dry_run`**。
- **级别② round-trip 双会话并行**：`vm1`/`vm2` 各起一份 notepad 到各自隔离桌面
  （`dao_vm1_notepad` / `dao_vm2_notepad`），`type_text → read_text` 读回一致：
  `roundtrip_vm1_match=true`、`roundtrip_vm2_match=true`（"DAO-VM1-道生一-777" /
  "DAO-VM2-一生二-888" 分别只出现在各自桌面）。
- **隔离真身实证**：`default_desktop_titles`（用户可见默认桌面）里**无任何这些 notepad**；
  两窗口只在各自隔离桌面 `EnumDesktopWindows` 里可见 → N 桌面 = N 互不干扰实例。
- **级别③ 取证**：`screenshot` 经 `PrintWindow`+DIB 落盘 `shot_*.bmp`（960×543），
  回传宿主可见 notepad 正文 —— 隔离桌面非输入桌面、屏幕 DC 截不到，但 PrintWindow
  让窗口自绘故可取证。

**关键排障链（供复现）：**
1. 桥以 **SYSTEM(session 0)** 跑时 `CreateProcessW` 到隔离桌面报 `WinError 5`（拒绝访问）
   —— session 0 起交互进程受限。**正解**：在**交互会话**内跑（本轮用 RDP 交互会话内
   python 直跑全栈）。
2. 主线程 `SetThreadDesktop` 报 `WinError 170(ERROR_BUSY)` —— 主线程已挂窗口。已把
   `attached()` 改 best-effort（见上 PR#13·3），主线程也能跑。
3. 非提权交互会话**写不了 `C:\` 根**（`Access denied`/`Errno 13`）；产物一律写
   `%USERPROFILE%`（`~\e2e_out.txt`），代码解压到 `~\dao_win`。

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

1. **桥进程应跑在交互会话而非 SYSTEM session 0**：本轮实证 session 0 内 `CreateProcessW`
   到隔离桌面报 `WinError 5`。落地方案二选一：(a) firstlogon 把桥改为**当前用户登录任务**
   （AtLogon/交互令牌），或 (b) 桥保持 SYSTEM 但用 `CreateProcessAsUser` + 会话用户令牌
   （`WTSQueryUserToken`）起隔离桌面进程。当前交互会话内直跑已全绿，收编到桥即完成闭环。
2. 级别③ 视觉模型接入：`PrintWindow` 取图已落盘，grounder 仍是注入契约，接真实视觉模型
   属后续工程。
3. mspaint 级别③ 真机取证同法可跑（本轮已验 notepad 截图链路）。
4. 长线：IddCx 虚拟显示器（级别② GPU 软件离屏）、vsix 插件端收编（参照 devin-remote）。

*道法自然 · 无为而无不为*
