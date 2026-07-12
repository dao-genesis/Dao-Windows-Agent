# 冷启动 Runbook · 全链路交接（真机趟通版）

> 给下一个 Agent：只读本文即可从全新 Linux VM（Devin Cloud 同构环境）零到一装出真实 Win10/11
> guest，并带出 Devin Desktop + 归一 VSIX + 机控桥 + 桌面级路由全链路。设计目标：**少等待、
> 少重复下载、少 token**——每阶段产物落盘即跳过，重复跑近零成本。
> （冷启动编排思路对齐 devin-remote `cloud/coldstart/`：一键、幂等、缓存优先、硬校验后落哨兵。）

## 一条命令

```bash
bash coldstart/up.sh            # 全链路（全新机首跑 ≈ 40-60 分钟，绝大头是无人值守装机）
bash coldstart/up.sh --status   # 只看现状（各阶段产物 + 桥/隧道探活）
bash coldstart/up.sh --run-only # 已装机，仅常态启动（≈ 1-2 分钟到桥就绪）
```

## 阶段 / 产物 / 哨兵（断点续跑判据）

| 阶段 | 产物（存在即跳过） | 首跑耗时 | 复跑耗时 |
|---|---|---|---|
| 1 QEMU/KVM | `qemu-system-x86_64` 可执行 + kvm 组 | ~2min | 0 |
| 2 介质 | `media/win11.iso`(5.1G)、`media/virtio-win.iso` | ~10min | 0 |
| 2b 置备载荷缓存 | `media/payloads/{vc_redist.x64.exe,py312.exe,VSCodeSetup.exe,DevinUserSetup.exe,RDPWrap.zip,rdpwrap_community.ini}` | ~3min | 0 |
| 3 镜像+应答盘 | `images/winlab.qcow2`、`images/winlab-unattend.iso`（捆入 bridge/core + VSIX + payloads） | ~1min | 0 |
| 4 无人值守装机 | `images/winlab.installed`（哨兵仅在 QEMU 正常退出 **且** qcow2 实占 ≥5GB 才落） | ~25-35min | 0 |
| 5 常态启动 | 桥 `127.0.0.1:19920/api/health` 返回 ok | ~2min | ~2min |
| 6 桌面路由 | guacd 4822 + WS 4823 + 令牌 4824（`desktop/up_desktop.sh`） | ~1min | 0 |

强制重做某阶段：删对应产物（如 `rm images/winlab.installed` 重装机、`rm images/winlab.qcow2` 重建盘）。

## 接入方式（装完即有）

- RDP `127.0.0.1:13389`（账号 `dao` / `Dao@2026!`，NLA 已关）
- 机控桥 `127.0.0.1:19920`（`Authorization: Bearer dao-win-lab`；调用用 `params` 不是 `args`）
- QMP `127.0.0.1:4444` · VNC `:0` · QGA `images/winlab-qga.sock`
- 桌面级路由：`desktop/test.html`（浏览器 canvas 直显真实 Windows 桌面，走 4824 令牌 → 4823 WS → guacd → 13389）

## guest 内首登置备（firstlogon.ps1 自动完成）

RDP/NLA → qemu-ga → Python 3.12（winget→离线兜底）→ VC++ 运行库 → pywinauto →
bridge/core 落地 `C:\dao_win`（清只读位）+ 计划任务登录自启（交互会话，勿改 SYSTEM）→
RDPWrap 多会话（先加 Defender 排除，社区 ini，重启 TermService）→ VSCode + 归一 VSIX →
Devin Desktop（官方 win32-x64-user 静默装）+ 归一 VSIX。
所有安装包**优先取应答盘 `payloads\` 缓存**（步骤 2b 预下），缺才在线下载。
日志：guest 内 `C:\dao-firstlogon.log`。

## 无头登录注入（rt-flow 本源移植·彻底规避 GUI）

Devin 登录不再靠人肉在 guest 里敲账密。两段式，**账密只经环境变量传入，永不入 ISO/命令行/日志/仓库**：

```bash
# 段一（宿主）：官方 password 端点换 auth1（不绕过·不伪造），产出 auth 束（仅 bearer·无密码·0600·已 gitignore）
DEVIN_ACCOUNT_EMAIL=... DEVIN_ACCOUNT_PASSWORD=... bash coldstart/up.sh --login
# → $HOME/.dao/devin_auth.json  （auth1 / userId / orgId / orgName·多账号各自隔离缓存·绝不串号）
```

段二（guest）：把 auth 束经桥投递到 `C:\dao_win\devin_auth.json`，再零键鼠注入：

```powershell
powershell -File C:\dao_win\coldstart-auth\devin-login.ps1 -AuthJson C:\dao_win\devin_auth.json
# 以远程调试口拉起浏览器/Devin Desktop → CDP 于 app.devin.ai 真源注入 auth1_session localStorage → 秒登
```

三件套（`coldstart/windows-sim/scripts/`，随盘落地 `C:\dao_win\coldstart-auth`）：
- `devin_auth.js`：官方 login + post-auth 取 org；`buildAuthBridge` 键名 1:1 对齐 `devin-remote/core/rt-flow/devin_proxy.js`（`auth1_session` + 迁移/known-org/last-internal-org/post-auth-v3 守卫键）。
- `devin_inject_cdp.js`：零依赖 Node WS 客户端连 CDP，导航真源→注入→复核 `hasAuth`。
- `devin_login.sh` / `devin-login.ps1`：宿主/guest 编排。
> 诚实边界：注入登录的是 Devin **网页/webview**（全功能）；Devin Desktop 原生 welcome-gate 仍需官方 first-party session，脚本不伪造不绕过。`file://` 写 localStorage 再跳转**无效**（源隔离），必须 CDP 真源注入或同源反代。

## 已趟过的坑（改动前必读）

1. **KVM 组不生效**：长寿命 shell 不刷新补充组 → `run_vm.sh` 自动经 `sg kvm -c` 启动；误退 TCG 会慢一个数量级。
2. **装机哨兵真伪**：SIGTERM 下 QEMU 也以 0 退出——必须校验 qcow2 实占 ≥5GB 再落 `*.installed`。
3. **pywin32 DLL 失败**：`ImportError: win32ui` = 缺 VC++ 运行库；且 pip 必须 `--no-user` 装全局 site-packages。
4. **ISO 拷入文件带只读位**：部署后必须清 `IsReadOnly`，否则热修不生效；改了 py 源记得删 `__pycache__`。
5. **RDPWrap 被 Defender 秒删**：装前先 `Add-MpPreference -ExclusionPath`；新 build 需社区 ini + 重启 TermService。
6. **Notepad 控件**：Win11 记事本编辑区是 `RichEditD2DPT`（不是 `Edit`）；级别② 必须走消息级 `uia_win` driver（osctl 只作视觉兜底，见 `core/profiles/builtin/__init__.py`）。
7. **Devin Desktop 登录**：安装/装插件全自动，但官方账号登录是 OAuth 回跳（`devin://`），必须真实 UI 登录，不能注入 state.vscdb；凭据经安全渠道提供，绝不入仓/入日志。
8. **归一 VSIX**：宿主态激活不得自启重 GUI（FreeCAD 懒启动）；webview 内变量不可被宿主激活路径引用（HA `AGENT_TOOLS` 教训）。

## 验证清单

```bash
python3 -m pytest tests -q                    # 级别① 纯逻辑（当前 104 passed）
bash ide/vscode/build.sh                      # 归一 VSIX 打包
bash coldstart/windows-sim/preflight.sh       # 宿主环境自检
bash coldstart/up.sh --status                 # 全链路现状
# 真机闭环（桥·隔离桌面 Notepad）：
# session.create → session.open_app(notepad) → invoke(open/type_text/read_text)
```
