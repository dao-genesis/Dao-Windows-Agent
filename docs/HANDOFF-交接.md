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

## 十一、路线A 阶段一真机全绿（本轮实证 · v0.2.2）

**guest VSCode 面板端到端全链路真机验收（全部 PASS，含录屏）：**
- 面板 `DAO 桌面`（v0.2.2）连接 → `已连接 ●`，Guacamole canvas 内渲染一路**独立** RDP 桌面。
- 键鼠双向直操：canvas 内开始菜单/记事本/cmd 全可用，键入文本落入面板会话。
- **多会话并行实证**：canvas 内 `qwinsta` → `console(ID1)` 与 `rdp-tcp#0(ID2)` 同为 `dao`、同时 Active，互不劫持（道并行而不相悖）。
- 稳定性：70s+ 空闲不掉线；`断开→连接` 重连**回到同一会话**（cmd 历史原样保留）。

**本轮致命修复（commit 8dd550f）：**
1. webview 内联脚本在模板字面量里写 `/^text\//` 正则 —— `\/` 被模板转义吞成 `/`，整段脚本 SyntaxError 报废（doConnect 未定义→连接按钮无效）。改 `indexOf('text/')`；`build.sh` 增加渲染后 `vm.Script` 编译自检，此类坑打包即拦截。
2. `desktop/tunnel/server.js` 监听地址软编码（`DAO_GUAC_BIND=0.0.0.0`）—— guest 经 slirp `10.0.2.2` 回连宿主隧道必需。

**真机踩坑（务必传承）：**
- **宿主 `/dev/kvm` 无权限时 run_vm.sh 静默回退 TCG** —— Win11 在 TCG(`-cpu max`) 下反复 `SYSTEM_THREAD_EXCEPTION_NOT_HANDLED` 蓝屏循环（软件模拟指令失真），像"磁盘损坏"实则不是。正解：`sudo setfacl -m u:$USER:rw /dev/kvm`（或入 kvm 组）后重启 VM，KVM 下 ~45s 稳定进桌面。
- 宿主经 VNC 快打字会丢 shift 字符（`Visual`→`isual`），非面板 bug；面板内键入无此问题。

**遗留（下一 Agent）：** ~~剪贴板双向透传回归、多 IDE 窗口=多路 RDP 并行实测、断线自动重连（指数退避已写，待真机回归）、git push 403 解封后推 PR~~ —— 已在阶段二全部完成（见下节）。

## 十二、路线A 阶段二真机全绿（本轮实证 · v0.2.2 + 隧道修复）

**阶段二回归（guest VSCode 面板内实测，全部 PASS，含录屏）：**
- **剪贴板双向透传**：canvas 内记事本 Ctrl+C → 宿主 IDE 编辑器 Ctrl+V 原文粘出；IDE 编辑器复制 → canvas 内记事本粘出，双向一致。
- **断开→重连回同一会话**：`断开` 后点 `连接`，记事本窗口与文本原样保留（RDP 会话未销毁，仅通道重建）。
- **多 IDE 窗口=多路 RDP 并行**：guest 内开第二个 VSCode 窗口（`ide_f5f2bc30`），其面板独立登录一路新会话；canvas 内 `qwinsta` → `console(1) + rdp-tcp#0(2) + rdp-tcp#1(3)` 同为 `dao` 且同时 Active，互不劫持。
- **空闲稳定性**：80s 空闲面板仍 `已连接 ●`，隧道无会话关闭。

**本轮致命修复（隧道 10s 掉线循环）：**
- 现象：面板连上后约 10s 即断，自动重连又断，无限循环（`会话打开/会话关闭` 交替）。
- 根因：`guacamole-lite` 默认 `maxInactivityTime=10000` —— 以"客户端→guacd 消息"计活跃，空闲桌面 10s 无输入即被 1011 踢线。**桌面会话本就该允许长时间无输入**。
- 修复：`desktop/tunnel/server.js` clientOptions 加 `maxInactivityTime: 0` 禁用；guacd 自身的 `User is not responding`（客户端不回 sync 才触发）保留，正常 Guacamole JS 客户端会回 sync 不受影响。
- 排障要诀：raw ws 探针（不回 sync）连 4823 能收到指令流但 ~10s 被 1011 关闭 → 一眼定位服务端 inactivity 踢线，而非 RDP/guacd 问题。

## 十三、路线A 阶段三真机全绿（后端控制面完整 · 本轮实证）

**定调（用户本轮重申）：前端面板为辅，后端控制面打通一切底层为主。** Agent 的核心操作一律走桥 `/api/session.invoke`（profile 动词分发），面板 canvas 仅作可视化辅助。本轮把 `system`（整机①底座）画像补齐为"覆盖整台 Windows 的后端控制面"，并在 guest 面板会话内逐一真机验证。

**`system` 画像动词（12 个，本轮由 7 → 12）：**

| 动词 | 说明 | 真机验证（guest DESKTOP-2DO81T8\dao） |
|---|---|---|
| `exec` | 跑一行 shell（Win→PowerShell） | `whoami`→`desktop-2do81t8\dao`；`$PID` 指向 guest powershell.exe（非宿主） |
| `read_file`/`write_file` | 读/写文本（自动建父目录） | 往返一致 |
| `list_dir` | 列目录 | `C:\` / `C:\dao_win` 条目正确 |
| `processes` | 列进程（可过滤） | tasklist 命中 guest 进程 |
| `env`/`sysinfo` | 环境变量 / 整机身份 | 通过 |
| **`download`** | 纯 stdlib 下载 URL 到磁盘 | 拉取 git README（3662 bytes）落盘成功 |
| **`install_pkg`** | winget 静默安装（`--source winget` 消歧 + 接受协议） | 真装 `7zip.7zip` 26.02 → `winget list` 列出、`C:\Program Files\7-Zip\7z.exe` 存在 |
| **`service`** | 服务 list/query/start/stop/restart（`*-Service`） | `Get-Service` 全量列出、`query Spooler` 详情通 |
| **`registry`** | 注册表 read/write/delete（reg.exe） | `HKCU\Software\Dao` 写→读→删闭环 |
| **`schtask`** | 计划任务 list/create/run/delete（schtasks.exe） | `DaoStage3` 建→列→跑→删闭环 |

**跨平台守约：** `download` 纯 stdlib，Linux/CI 用 `file://` 真跑真测（新增单测 `test_system_backend_verbs`）；`install_pkg/service/registry/schtask` 为 Windows 专属，非 Windows 明确降级提示，非法 `action` 平台无关一律拒绝。core 仍零第三方依赖。

**踩坑与正解：**
- 桥进程常驻 `C:\dao_win`（非仓库工作区），改画像后需 `Copy-Item` 覆盖 + 重启 `start-bridge.ps1` 才生效；工作区路径无写权限（PermissionError），走 `C:\tmp` 中转。
- winget 首装报 `0x8a15005e msstore 证书不匹配` 致包源歧义 → 固定 `--source winget` 解决。
- guest 为 TCG 软件模拟，冷 PowerShell 首跑慢：`Get-Service` 全量需 >60s，故 `service` 默认 timeout 提到 180s。

*道法自然 · 无为而无不为*

## 十四、归一插件融合 + Devin Desktop 真机（本轮 · PR#17/18/19 · 实况交接）

> 本轮聚焦：把 FreeCAD/KiCad/嘉立创EDA/Home Assistant 四领域**归一进单一 Windows 插件与单一 Cascade**，
> 并在**真 Win11 QEMU/KVM guest + Devin Desktop** 内端到端验证。以下**严格区分 PASS / 部分 / 未验**，
> 不夸大：整个流程**未全绿**，仍有实测缺口，交给下一个 Agent 继续。

### 14.1 已合入 / 已开 PR

| PR | 内容 | 状态 |
|---|---|---|
| #17 | 归一补全：FreeCAD/嘉立创/HA 领域塑形器登记进宿主分派器 `__DAO_UNIFIED_HOST__`；firstlogon 盘符自适应（D:–G: 扫描） | ✅ 已合 |
| #18 | firstlogon.ps1 加 UTF-8 BOM（PS 5.1 无 BOM 按 ANSI 解析中文注释里 U+2014 尾字节致整脚本 ParserError，真机复现） | ✅ 已合 |
| #19 | firstlogon Resolve-Python 排除 `\WindowsApps\` 商店占位 stub（Get-Command python 命中 0 字节别名致离线兜底被跳过、桥指向假 python，桥 9920 永不监听，真机复现） | ⬅️ 开·CI 6 绿·可合 |

### 14.2 归一架构（代码层已落地，PR#17）

- **单一宿主**：`ide/vscode` 主插件暴露 `globalThis.__DAO_UNIFIED_HOST__`；四领域子插件 `vendor/`
  被 `build.sh` 自动收编进同一 VSIX（252 文件 1.77–1.85 MB）。
- **单一 Cascade**：子插件检测到宿主存在即**只登记 `registerDomainShaper(app_id, {wrap,status,toggle})`**，
  **不再另起第二个 Cascade**；宿主缺失时才回退独立基底（standalone 仍可用）。`unify.js` 过滤
  `*-cascade`（≠`daoWin-cascade`）子容器与 `<ns>.cascade` 子项。
- **动态领域模式**：`core/agent/modes.py` 按 registry 非通用 profile 生成 `domain:<app_id>`；
  `~/.dao/mode.json` 持久化；`native`/`coding` **不注入领域 overlay**。
- 四领域 app_id：`freecad` / `kicad` / `jlceda` / `homeassistant-ext`。

### 14.3 真机实测结论（本轮·Win11 26100 guest）

**离线自检（宿主 Linux，可复现）**：`python3 -m pytest tests -q` → **98 passed**；
`bash ide/vscode/build.sh` → `dao-windows-agent-0.7.1.vsix` 打包成功。

| 项 | 结果 | 证据/说明 |
|---|---|---|
| Win11 KVM guest 启动 + 桌面 | ✅ | Remmina VNC 127.0.0.1:5900 见 Win11 桌面（License expired 评估版，不影响功能） |
| 冷启动桥自启（掉电重启后） | ✅ | VM 重启后 `DaoBridge` 计划任务拉起桥，15s 内 `/api/health` ok（apps=browser/freecad/jlceda/kicad/mspaint/notepad/system） |
| 桥后端全链 | ✅ | health / mode.list / mode.set / 领域裁剪 / open_app 均通 |
| 领域裁剪 domain:freecad | ✅ | allowed_apps 仅 [browser,freecad,system]；open_app kicad 被拒（"不开放应用"错误）——正确 |
| coding 机控隔离 | ✅ | coding 下 allowed_apps 空、open notepad 被拒 |
| Devin Desktop 安装 | ✅ | 静默装到 `%LOCALAPPDATA%\Programs\Devin\Devin.exe`（windsurf-stable latest 元数据端点） |
| Devin Desktop 登录 | ✅ | yzyozwl49 账号登录成功（凭据经 guest 剪贴板传入，未落任何仓库/日志/报告） |
| Devin Desktop 工作台 | ✅ | 清旧进程后 `devin://` 深链启动，Agent/Editor 工作台打开 |
| **归一 VSIX 装入 Devin Desktop** | ✅ | `devin-desktop.cmd --install-extension dao-windows-agent-0.7.1.vsix` → "successfully installed"（VSIX 经宿主 http.server + slirp 10.0.2.2 传入 guest） |
| **单一 Cascade（Devin Desktop 内）** | ✅（目视） | Editor 模式左侧仅一个 `DAO · AI 交互: Cascade · 三模式` 容器；底栏见 `DAO ide_7de70ab6 ● / 主模式 / HA 未连接 / 嘉立创EDA工程 / 道之对话(LCEDA AI)` 状态项，无重复 Cascade 面板 |
| FreeCAD GUI | ⚠️ 部分 | 经桥起 FreeCAD 1.0.2 窗口可见并交互（Welcome 页），但 OpenGL 软渲染告警存在（KVM 无 GPU） |
| Notepad UIA type_text | ❌ | Win11 新版 Notepad profile 与 UIA 不匹配：find/set_value 失败（桥通、profile 待适配） |
| `native` 模式 | ⚠️ 缺失 | 动态模式列表无 `native`；现为 `primary`/`coding`/`windows`/`domain:*`，需确认 `native` 应否新增或 `primary` 即其替代 |
| `homeassistant-ext` 能力 | ⚠️ 缺失 | guest `/api/apps` 未列 homeassistant-ext（塑形器已登记，但后端 registry 未暴露该 app）——待排查 |
| KiCad / 嘉立创EDA / HA 完整 GUI 金路径 | ❌ 未验 | 仅后端可达，未做完整 GUI 工作流 |
| MCP 注册/工具调用 · 桌面路由 · RDP(13389) · QGA | ❌ 未验 | 本轮未覆盖；QGA guest-ping 超时（socket 路径存在但无响应） |
| 全新冷启动零人工（不手工触发任务/装 Python） | ❌ 未验 | 现有 guest 已修好；#19 修复需在**全新** unattended 装机跑一遍才算闭环 |

### 14.4 交接给下一个 Agent（按优先级）

1. **合 PR#19** 后，跑一次**全新** `coldstart/up.sh` 无人值守装机，验证 #17/#18/#19 三修复叠加下
   桥**零人工**自启（真 Python + BOM + 盘符自适应全生效）。
2. 排查 `homeassistant-ext` 未进 `/api/apps`：确认 HA profile 是否被 registry 加载（可能 profile
   注册条件/依赖缺失），补齐后领域模式 `domain:homeassistant-ext` 才可用。
3. 定夺 `native` 模式：要么在 `core/agent/modes.py` 新增，要么在文档/状态栏明确 `primary` 即通用替代。
4. 适配 Win11 新版 Notepad 的 UIA profile（或改走消息级 driver），使 open→type_text→read_text 往返绿。
5. KiCad / 嘉立创EDA / HA 完整 GUI 金路径 + 提示词隔离的 **Cascade UI 直证**（本轮仅后端证隔离）。
6. MCP 注册/工具调用、桌面路由（guacamole 链路）、RDP(13389)、QGA 逐项真机验证。

### 14.5 环境值增量（本轮）

- 本 Devin VM 内存仅 7 GB、VM 用 4 GB：**QEMU 进程易被回收/掉电**；每次重启前务必
  `sudo setfacl -m u:$USER:rw /dev/kvm`（否则回退 TCG → Win11 蓝屏循环），再
  `bash coldstart/windows-sim/run_vm.sh`，桥约 15–45s 就绪。
- Devin Desktop 装/登流程见 `devin-remote/cloud/coldstart/coldstart.ps1`；登录账号 yzyozwl49
  （密码见账号总表，**不入仓**）。
- VSIX 传 guest：宿主 `python3 -m http.server <port>` + guest `iwr http://10.0.2.2:<port>/xxx.vsix`
  （比 base64 分块经桥更稳，本轮 base64 分块因 chunk 请求体过大 ok:false，改 http.server 一次成功）。

*道法自然 · 无为而无不为*
