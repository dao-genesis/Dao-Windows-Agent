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
| PR#13 | **消息级本源 driver（纯 ctypes，弃 pywinauto/pywin32）+ 真机 live 全绿** | ✅ |
| PR#14 | **桥改交互会话(WinSta0)自启 → 经桥 HTTP 端到端隔离 round-trip 全绿**；闭合 SYSTEM(session0) 跨窗口站死结 + 截图路径软编码单测 | ✅ |
| PR#16 | **VSCode 插件前端（ide/vscode）**：每个 IDE 窗口=隔离会话，自带 runtime 可自启桥；**一键冷启动编排 `coldstart/up.sh`**（幂等断点续跑）；firstlogon 自动装 VSCode+插件 | ⬅️ |

离线自检：`python3 -m pytest tests -q` → **31 passed**（级别①②③ 全部 dry-run 可测，Linux 即可）。

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

## 六、PR#14 本轮闭环（经桥 HTTP 端到端·根因修复）

**根因（跨窗口站死结）**：桥若跑在 **SYSTEM / session 0**（服务窗口站 `Service-0x0`），其
`CreateDesktop` 建的隔离桌面属 session 0 窗口站；而 `CreateProcessAsUser` 用交互会话用户令牌
起的进程落在 **交互会话 WinSta0**——两个窗口站互不可见，故 notepad 起来了(`pid` 有)、
隔离桌面里却 `EnumDesktopWindows` **永远枚举不到**(`found:false`/`编辑控件未定位`)。
令牌桥接(方案 b)治标不治本。

**正解（方案 a·已落地）**：桥必须与其隔离桌面 **同处一个窗口站** → 让桥跑在**交互会话**。
把 `DaoBridge` 计划任务从 `SYSTEM/AtStartup/ServiceAccount` 改为
`当前登录用户/AtLogOn/LogonType Interactive/RunLevel Highest`（见 `firstlogon.ps1`）。
桥遂在 `SessionId=1·WinSta0` 内 `CreateDesktop`+`CreateProcessW`，隔离桌面窗口即可枚举。

**真机 live 全绿（经桥 HTTP `POST /api/session.*`，纯 IDE 内）**：
- python `SessionId=1`、`whoami=...\dao`（确认桥在交互会话）。
- `vmA`：open→type_text→read_text 读回 `道法自然 dao-win e2e OK 20260708`（edit hwnd 命中）。
- `vmB`：另起一份 notepad 写 `second isolated session VMB 111`；写 vmB 后 **vmA 读回不变** → 双会话互不干扰。
- 默认桌面（QMP 控制台截屏）里**无任何这两个 notepad** → 零用户可见干扰。
- `screenshot` 经 `PrintWindow` 跨桌面取到 vmA 隔离桌面 notepad 正文，落 `%TEMP%`（软编码，非 `C:\` 根）。

**Devin Remote 多 RDP 成果的整合结论**：不搬 RDPWrap/多账号/多 RDP 会话那套（用户明令规避其配置负担），
而是把「N 个互不干扰实例」这一**目标**用**单账号内 N 张 `CreateDesktop` 隔离桌面 + 消息级 I/O**
达成——同效果、零配置、去中心化。多 RDP 骨架仅作对照，不引入其账号/会话管理复杂度。

**级别① 整机底座真机跑通**：经桥 `system` profile 在 guest 真跑 `sysinfo/exec/write_file/read_file/processes`
（Win11 26100·PS 5.1·文件往返一致）——对标 Agent 在自己 Linux VM 上的 `exec/file/ls/ps`，
把整台 Windows 无头、天然隔离地做进 IDE。

**新增单测（26 passed）**：`test_win_desktop_session_aware_launch_surface`（会话自适应起进程接口面）、
`test_uia_win_screenshot_path_softcoded`（截图目录软编码：默认 `tempfile.gettempdir()`，显式 `dir` 覆盖，绝不硬编码 `C:\` 根）。

**对现存 guest 的热修**：桥跑 SYSTEM 时可零 UAC 自我重构——用其 `system` profile 写 `reconfig.ps1`、
以独立一次性任务 `schtasks /Run` 拉起（不作桥子进程，杀旧桥不误伤），重注册 `DaoBridge` 为交互任务并 `/Run`。

## 五、下一步（按优先级）

1. ~~桥进程应跑在交互会话而非 SYSTEM session 0~~ **✅ 已闭合（PR#14，见第六节）**。
2. 级别③ 视觉模型接入：`PrintWindow` 取图已落盘，grounder 仍是注入契约，接真实视觉模型
   属后续工程。
3. mspaint 级别③ 真机取证同法可跑（本轮已验 notepad 截图链路）。
4. ~~vsix 插件端收编~~ **✅ 已落地（PR#16，见第七节）**。
5. 长线：IddCx 虚拟显示器（级别② GPU 软件离屏）。

## 七、PR#16 本轮：IDE 前端 + 冷启动固化

**ide/vscode 插件（把整台 Windows 做进 IDE 的前端落地）**：
- 激活即为本窗口分配稳定隔离会话 `ide_<hash>`（绑定工作区路径），N 个 IDE 窗口 = N 个互不干扰实例。
- 面板全部一键按钮（真机 RDP 打字乱码的规避）：级别① system exec/sysinfo/processes、级别② notepad 隔离桌面 round-trip、级别③ PrintWindow 截图、search_verbs。
- 零配置冷启动：连不上 `daoWin.bridgeUrl`（默认 9920）时，用打包时捆入的 `runtime/`（bridge+core）自启本地桥（9930）。
- 打包：`bash ide/vscode/build.sh` → `dao-windows-agent-0.1.0.vsix`（纯 stdlib+node 无三方依赖）。

**冷启动固化（针对"前两轮冷启动太慢"痛点）**：
- `coldstart/up.sh` 一行从零到可用：装 qemu→取介质→建镜像→无人值守装机→常态启动→等桥就绪；每阶段产物落盘即跳过（幂等），`--status`/`--run-only` 可单独用。
- `build_image.sh` 把 vsix 捆进应答盘；`firstlogon.ps1` 装机即自动装 VSCode（winget 钉 `--source winget` 防 msstore 歧义）+ 离线装插件 —— 冷启动完成即得可用 IDE 前端。

## 八、PR#16 真机全量验收（本轮实证）

**桥 API 全量（宿主经 `127.0.0.1:19920`，17/17 PASS）**：health/apps、级别① system
sysinfo/exec/write_file/read_file/processes、级别② notepad open→type_text→read_text
round-trip、双会话并行隔离（数据+PrintWindow 视觉双证，默认桌面零 notepad）、session destroy。
冷启动重启后桥 **30s 自动就绪**（KVM），全套幂等复测通过。

**VSCode 插件 GUI 真机验收（Win11 guest 内实际点击，全绿）**：
- 激活即状态栏 `DAO ide_<hash> ●`（桥已连+会话已建，零点击冷启动）；点状态栏一键开「DAO 虚拟机面板」。
- 面板按钮实测：健康检查/已装应用/创建会话/会话列表 ✓；sysinfo（Windows-11-10.0.26100）✓；
  在隔离桌面开记事本→写入文本→读回一致（`道法自然 DAO IDE 隔离会话 OK`）✓；PrintWindow 截图取证 ✓。
- 服务端 `session.list` 同步可见 `ide_370de318` —— IDE 窗口=隔离会话闭环实证。

**本轮修复（已入 PR#16）**：
1. `package.json` 声明 `capabilities.untrustedWorkspaces.supported=true` —— 否则 VSCode
   受限模式（未信任工作区）直接不激活插件，命令面板搜不到任何 DAO 命令（真机踩坑）。
2. 面板 `session.invoke` 遇「先 open_app」错误自动 create+open_app 后重试一次；
   `open_app` 按钮注册后立即执行 `open` 动词真正把窗口起到隔离桌面（原实现只注册不开窗，
   read_text 报「编辑控件未定位」）。
3. `run_vm.sh` 加 `-device qemu-xhci -device usb-tablet`（绝对坐标指针）——否则 PS/2
   相对鼠标经 VNC 漂移，宿主对 guest 的 GUI 点击完全不可靠；QMP `send-key` 打键盘、
   usb-tablet 打鼠标是驱动 guest GUI 的最稳组合（RDP 打字乱码，弃用）。

**驱动 guest 的正解沉淀**：headless 一律走桥 `system.exec`；GUI 键盘走 QMP
`send-key`（`/tmp/qmpkey.py` 模式）；GUI 鼠标依赖 usb-tablet 绝对坐标；guest 拉文件走
`http://10.0.2.2:<port>`（宿主 http.server）。

## 九、正本清源 · 本源修正（最新一轮定调 · 优先级最高）

> **⚠️ 先读 [`正本清源-桌面级路由本源.md`](正本清源-桌面级路由本源.md)。** 与前八节冲突处以该文为准。

用户本轮明确指出前几轮方向"从底层就说错了"：**面板不该是文字/按钮层**（第八节的按钮面板实证仍有效，
但**降级为"控制面/调试形态"**，非最终前端）。**新本源**：IDE 装插件后，**面板里直接就是整台 Windows 的
桌面本体**——整块 GUI、所有软件、所有操作与用户真机完全一致，走 **RDP/RemoteApp 原生远程桌面协议级
（类多 RDP）** 把一路**真实、独立、可交互**的桌面会话路由进面板（**不是投屏/截图推流**）。
每开一个 IDE 窗口 = 一路独立完整桌面，单账号、并行、互不干扰。

**本轮交付（本 PR）**：仅**定调 + 调研 + 去芜存精**（用户要求先整理好交给后续 Agent，不强求全量实现）——
新增 `正本清源-桌面级路由本源.md`；修正 `AGENTS.md` 第一节；`ide/vscode` 按钮面板标注为 `legacy-control-panel`；
`coldstart/README.md` 增桌面路由待固化清单。

**后续 Agent 主干（按正本清源文档第五节）**：① 冷启动 VM 内固化 `rdpwrap`（+组策略单会话修正）验证单账号多路 RDP；
② 起 `guacd` 打通 RDP→Guacamole，`guacamole-common-js` 嵌 Webview 渲染一路桌面；③ 插件 `ide_<hash>` 稳定映射一路会话、零点击拉起；
④ 多窗口并行 + 输入/剪贴板/多显/DPI/重连打磨。**复用**：`coldstart/`、`bridge/`(转控制面)、`tests/`、profile 机制。

*道法自然 · 无为而无不为*

## 十、路线A 桌面级路由实现（本轮实施）

> 正本清源后的首次全量实现。核心链路：
> VSCode Webview (guacamole-common-js canvas) → WS 隧道 (guacamole-lite) → guacd (Docker) → RDP → Windows 桌面

**新增文件：**
- `desktop/tunnel/server.js` — WebSocket↔guacd 隧道 + 令牌铸造 HTTP（guacamole-lite，加密 token 不泄漏 RDP 凭据）
- `desktop/guacd.sh` — 幂等拉起 guacd Docker 容器
- `desktop/up_desktop.sh` — 一键拉起路线A 全链路（guacd + tunnel）
- `desktop/test.html` — 浏览器端到端测试页（统用 guacamole-common-js）
- `ide/vscode/media/guacamole-common.min.js` — 内嵌 guacamole-common-js 1.5.0（Apache-2.0）

**修改文件：**
- `ide/vscode/extension.js` — 新增 `daoWin.openDesktop` 命令（主前端桌面路由面板），旧按钮面板降级为 `openPanel`（辅助控制面）
- `ide/vscode/package.json` — v0.2.0，新增桌面路由配置项（tunnelHttpUrl/tunnelWsPort）
- `coldstart/windows-sim/scripts/firstlogon.ps1` — 新增第5节 rdpwrap 安装+多会话配置

**链路说明：**
1. `guacd`（Docker `guacamole/guacd:1.5.5`）监听 4822，把 RDP 协议翻译为 Guacamole 指令流
2. `desktop/tunnel/server.js` 监听 WS 4823 + HTTP 4824；HTTP `/token?ide=ide_xxx` 铸造加密连接 token（AES-256-CBC），凭据只在服务端；WS 解密 token、连 guacd、双向中继
3. VSCode Webview 加载 guacamole-common.min.js，创建 `Guacamole.Client` + `WebSocketTunnel`，canvas 渲染桌面，键鼠直操
4. `ide_<hash>` 映射：每个 IDE 窗口的工作区 SHA1 前8位 = 稳定会话 ID，每次开桌面自动获取该会话对应的加密 token，零点击连接
5. rdpwrap + `fSingleSessionPerUser=0`：单账号多路 RDP，每个 IDE 窗口获得独立桌面会话

**后续 Agent 待打磨：**
- 多窗口并行实测双路 RDP 会话并行互不干扰
- 输入法/剪贴板透传（Guacamole clipboard API）
- 多显示器/DPI 自适应（resize-method: display-update 已启用）
- 会话重连/断线恢复
- guacd 折进容器编排（docker-compose 或 K8s sidecar）

*道法自然 · 无为而无不为*
