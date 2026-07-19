# 兜底 · 通用型 AI 配置 Runbook — 任意 Windows 一文流式配完「多 RDP 接入」

> 道法自然 · 无为而无不为。**本文是「发给本地 Agent 的一份通用兜底文档」**：不管用户是哪版 Windows、
> 有无管理员、是否入域、有无杀软/防火墙、家用 NAT 还是公网，**AI（经 DAO Bridge / MCP 连上这台机器）
> 照本文一步步执行，即可把「同机连接自己其他 Windows 账号的多路 RDP」配到可用**，并把 RDP 客户端
> 反向路由进插件面板。
>
> **定位（务必看清）**：
> - 这是**兜底 + 自动化的蓝本**，不是「每次都要人肉发文档」。核心目标始终是**不断降低用户成本**——
>   本文的每一步都应逐步固化成插件内的自动化流程；自动化失效时，本文即人可读、AI 可执行的**最后保障**。
> - **只在用户明确授权后对其机器做变更**。本文所有「写入/安装/改策略」步骤默认 **dry-run 先行**，
>   逐档征询同意；未获同意只做**只读探测**。
> - 工程资产已就位：`vm-replica/`（`vm_host_daemon.py` / `vm_inner_agent.py` / `mcp_server.py` /
>   `ts_multifix.py`）+ `core/environment.py`（探测/选路）。本文是「把它们按环境正确编排」的操作总纲。
> - 与 [`调研-任意环境接入-方法全景与装即用边界.md`](调研-任意环境接入-方法全景与装即用边界.md) 的分层架构（Basic①/Enhanced②/Session②'/Strong③/Coldstart Z）一一对应；本 Runbook 专攻 **②' 会话级（多 RDP）** 的落地。

---

## 〇、总原则（AI 执行前先读）

1. **先探测，后决策**：任何写操作前，先跑只读探测（第一步），据结果走决策树，**绝不盲目执行命令**。
2. **幂等 + 可回滚**：每个写步骤都要能重复执行不出错，且都登记到回滚清单（第九节），随时能「还原到就像没配过」。
3. **不碰用户既有资产**：不改用户已有的 RDP 配置项本身（只**增加**并发/新会话），不动用户文件，
   不登出/最小化用户自己的会话，测试只用专属新文件 + 唯一 tag（§教训来自 `vm-replica/HANDOFF_NEXT_AGENT.md`）。
4. **诚实降级，不假装成功**：某档配不了（无管理员/Home 无原生 RDP/域禁用/杀软拦截），**如实报告并降级**
   到更低档或 coldstart(Z)，绝不谎报「已配好」。
5. **凭据安全**：账号密码等只在本机内存/本机配置文件（`C:\ProgramData\dao_vm\config.json`），
   **绝不写入仓库、日志、PR 或发回云端**。

---

## 一、Step 0 · 只读探测（永远第一步，零副作用）

用 `core/environment.py`（或等价 PowerShell）采集，**不写任何东西**：

```powershell
# 语言中立的版本/版次判定（勿用英文 caption 子串——中文系统会全 false，见 HANDOFF §14.5）
$os = Get-CimInstance Win32_OperatingSystem
$os.Caption; $os.OperatingSystemSKU; $os.ProductType   # ProductType:1=工作站,2=域控,3=服务器
$os.BuildNumber
# 管理员？
([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrators')
# 入域？
(Get-CimInstance Win32_ComputerSystem).PartOfDomain
# RDP 开关 & 单会话限制
Get-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections
# termsrv.dll 二进制版本（决定 RDPWrap/ts_multifix 偏移是否命中）
(Get-Item C:\Windows\System32\termsrv.dll).VersionInfo.FileVersion
# 现有会话
qwinsta
# 杀软
Get-CimInstance -Namespace root\SecurityCenter2 -Class AntiVirusProduct -EA SilentlyContinue
```

**判定输出**（喂给决策树）：`family`(Home/Pro/Edu/Ent/Server) · `is_admin` · `part_of_domain` ·
`rdp_enabled` · `termsrv_version` · `rdpwrap_can_match`(偏移表/ini/自发现能否命中) · `av_present`。

> 版次识别铁律：**用数字 `OperatingSystemSKU` + `ProductType`，不用 caption 英文子串**。SKU 为 None 才回落
> caption（含中文「教育/企业/家庭/专业」）兜底。此为 141 中文 Win11 教育版真机暴露并修复的缺陷。

---

## 二、决策树（探测结果 → 走哪条路）

```
┌ ProductType=3 (Server) ────────────────► 路 S：RDS/原生多会话（默认2会话即够则免装角色）
│
├ 工作站(ProductType=1)
│   ├ is_admin = false ───────────────────► 路 N0：无提权 → 只能 Basic①(应用多开+CreateDesktop+无头)
│   │                                          或引导用户提权；多 RDP 档不可达 → 记录并降级/Z
│   ├ part_of_domain = true 且 组策略禁 ────► 路 D：域策略阻断 → 降级 Basic① 或 coldstart(Z)，如实告知
│   ├ family ∈ {Pro,Edu,Ent} ──────────────► 路 P：开原生 RDP + 默认1并发；需 >1 并发时叠 RDPWrap/ts_multifix
│   └ family = Home ────────────────────────► 路 H：无原生 RDP host → 必须 RDPWrap/ts_multifix（增强档·需知情同意）
│
└ 任一路「配不成/用户拒绝提权/杀软硬拦」──────► 路 Z：coldstart 我方 QEMU/KVM Win VM 兜底
```

---

## 三、路 P（Pro/Edu/Ent · 最顺）

### P1. 开启原生 RDP（可逆，仅改注册表 + 防火墙）
> 先 dry-run 报告将改动项，获同意再执行。若 `rdp_enabled` 已开，**跳过**（不重复改用户配置）。
```powershell
# 回滚点：记录原 fDenyTSConnections 值
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
Enable-NetFirewallRule -DisplayGroup 'Remote Desktop'
# 保留 NLA（更安全）；仅当客户端不支持 NLA 才按需关闭并告知风险
```
校验：`(Get-ItemProperty ... fDenyTSConnections).fDenyTSConnections -eq 0` 且 `qwinsta` 列出 rdp-tcp 监听。

### P2. 需要「同账号/同机多路并行」（>默认1路）
- Pro/Edu/Ent 默认「单用户单会话」。要多路并行 → 用 `vm-replica/agent-vm/ts_multifix.py`
  **运行时内存补丁**（不改磁盘 `termsrv.dll`，可 revert，抗更新），或社区 RDPWrap。**属增强，需知情同意 + 杀软放行。**
- `ts_multifix` 偏移三级级联：内置 OFFSETS（精确版本）→ rdpwrap.ini（社区数百 build）→ **签名扫描自发现**；
  三者都不命中则 **no-op 不盲写**（安全）。Server SKU 自动 no-op（原生多会话）。

### P3. 建/复用「分身账号」当会话
```powershell
$pw = ConvertTo-SecureString '<强随机>' -AsPlainText -Force   # 密码只留本机 config.json
New-LocalUser -Name 'daovm01' -Password $pw -PasswordNeverExpires -AccountNeverExpires
Add-LocalGroupMember -Group 'Remote Desktop Users' -Member 'daovm01'
# 回滚：Remove-LocalUser + 删 profile（仅限"我们创建的"账号，绝不动用户既有账号）
```
> 单账号也可走 vm-replica 的「本地全量复刻」派生分身，与主账号数据可共享/隔离（用户要「底层数据可共享」时用 junction 挂共享目录）。

### P4. 回环发起 RDP 会话（绕自连限制 + 屏外保活）
```powershell
cmdkey /generic:TERMSRV/127.0.0.2 /user:daovm01 /pass:<pw>
mstsc /v:127.0.0.2 /w:1280 /h:800
```
- 由 `vm_host_daemon.py` 拉起并**离屏保活**：取消最小化 + 移屏外 + `SWP_NOACTIVATE`（不抢用户焦点、
  仍可截图/输入）。这是 HANDOFF §6#1 修复的核心（否则最小化会话被 Windows 挂起 → 截图全黑/吞键）。

---

## 四、路 H（Home · 无原生 RDP host）

- Home **没有 RDP host**，`_ensure_rdp_enabled()` 先写 `fDenyTSConnections=0`+NLA+防火墙（可逆，Home 必需），
  但**仍需 RDPWrap/ts_multifix 提供 host 能力 + 多会话**。
- **这是「增强档」，必须知情同意**：向用户说明「RDPWrap 是第三方内存补丁、Windows 更新后可能需重新匹配、
  杀软可能报毒」，并提供**一键卸载/还原**。默认**不自动下载**第三方二进制；如需，走校验（哈希/来源）+ 用户确认。
- 配不成（用户拒绝/杀软硬拦/偏移不命中且自发现失败）→ **降级 coldstart(Z)**，如实告知「本机 Home 版无法零风险配多会话」。

---

## 五、路 S（Server）

- Server 默认允许 2 个会话——**若 2 路够用，什么都不用装**，直接 P3/P4 建号连接。
- 需 >2 路 → 装 RD Session Host 角色（**需重启** + RDS CAL，120 天宽限期），或同样走 `ts_multifix`（Server SKU 会 no-op，
  此时应走 RDS 官方路）。域环境需 RD Licensing。

---

## 六、路 N0（无管理员）/ 路 D（域禁用）

- **无管理员**：RDP 开关、RDPWrap、驱动、建账号大多需提权 → **只能 Basic①**（应用多开 + CreateDesktop + 无头）。
  引导用户提权是可选项；否则如实降级。
- **域机**：组策略可能禁 RDP/禁建本地账号/禁装驱动 → 探测到阻断即降级 Basic① 或 Z，**明确告诉用户「受域策略限制」**，
  不尝试绕过组策略（合规红线）。

---

## 七、路 Z（coldstart 兜底 · 永不失败的底）

- 上述任一路配不成 → 在**我方 Linux VM** 上用 `coldstart/windows-sim`（QEMU/KVM）跑干净 Win10/11，
  在其中配好多会话，面板路由到它。**不依赖、不修改用户真机**；代价是云端资源/延迟 + 用户数据出本机需明确同意。

---

## 八、把 RDP 客户端「反向路由进插件面板」（本源前端）

> 用户要点：Windows 远程桌面连接本身也是官方软件，**直接反向路由进插件面板**，用户在插件内即可配置一切，
> AI 也在同一面板内代操作。思路与 dao-bridge（cloudflared 内穿）互通——**零配置打通 + 一键化 + 原生集成/快速下载**。

1. **会话产生**（第三～七节）：在用户机上造出 N 路真 RDP 会话（daovm01/02…，各自完整独立桌面）。
2. **传输/渲染**：`RDP → guacd(Guacamole) → WebSocket → 插件 Webview 内 canvas`（`guacamole-common-js`）。
   备选前端 FreeRDP(WASM)/noVNC。**每个 IDE 窗口按 `ide_<hash>` 稳定映射到一路会话**，首开零点击拉起 + 渲染。
3. **AI 同面板代操作**：AI 经 `mcp_server.py` 的 23 个 `vm_*` 工具（exec/screenshot/click/type/key/…）
   驱动**同一路会话**，与用户在面板里看到的完全一致 → 所见即所得、可记录可回放。
4. **网络可达**：家用 NAT 下经 dao-bridge 隧道（cloudflared + ntfy mesh 兜底、自愈自反注入）暴露到云端，
   不需公网 IP/不改路由器。**把「市面成熟但配置繁琐的多 RDP 内穿」一键化、原生化。**
5. **静默/零足迹**：不用时 `host.hibernate` → revert termsrv 补丁 + 删「我们建的」账号 + 关我们开的 mstsc +
   清临时文件，`footprint=zero`，**用户日常状态完全无损**（HANDOFF §15 真机跑通「太上下知有之」）。

> **一次配好、处处复用**：多 RDP 基底一旦打通，用户所有软件都能在这路原生桌面里像本地一样打开操作——
> FreeCAD/KiCad 等**已适配软件**用其专属 profile 加速，**未适配的任意第三方软件**也能靠 AI GUI 操作兜底，
> **无需为每款软件单独解锁**。这正是「做一套通用体系」的价值。

---

## 九、回滚清单（任何时候「还原到就像没配过」）

AI 执行任何写步骤时**同步登记**，`host.hibernate` 或用户请求还原时逐条逆操作：

| 写操作 | 回滚 |
|---|---|
| `fDenyTSConnections=0` | 还原为原记录值（若原本就是 0，不动） |
| 开防火墙 Remote Desktop 组 | 若原为关，则 `Disable-NetFirewallRule` |
| `ts_multifix` 内存补丁 | `revert`（`bServerSku`/`cdefpolicy_jne` 还原，`applied=False`） |
| RDPWrap 安装 | 官方 uninstall + 删服务补丁 |
| `New-LocalUser daovm*` | `Remove-LocalUser` + 删 profile（仅限我们建的账号） |
| `cmdkey` 凭据 | `cmdkey /delete:TERMSRV/127.0.0.2` |
| 我们拉起的 mstsc | 仅 kill 命中 `TscShellContainerClass`+我们的目标（不误伤用户自己的远程连接） |
| `C:\dao_vm\` 临时/计划任务 | 删 `start_*.bat`、注销 `dao_agent_*` 计划任务 |
| 虚拟显示器驱动（若装） | 卸载驱动（可能需重启） |

**红线**：不删用户既有账号、不断用户 console、不改用户既有 RDP 配置本身、不动用户文件。

---

## 十、AI 参与度递减路线（最终固化为自动化）

1. **L3 · 全 AI 逐步**（现状）：AI 读本文，探测→决策→逐命令执行→校验→回滚登记，全程接管（参与度最高）。
2. **L2 · 半自动**：把稳定步骤固化进 `vm_host_daemon`/插件（探测选路、开 RDP、建号、连接、保活、guacd 渲染），
   AI 只处理异常分支（杀软放行、偏移不命中、域阻断的降级决策）。
3. **L1 · 一键**：打包「一次性冷启动安装器」（工具链 + RDP 配置 + 三组件 exe），用户一键跑完；
   AI 仅在失败时按本文兜底介入。
4. **L0 · 装即用**：插件安装即静默完成基础档①，多会话档在用户首次需要时一键征询同意后自动配好。

> 每前进一级，用户操作成本下降一层，本文永远作为**最底层兜底蓝本**（自动化失效时人/AI 照此手工配通）。

---

## 十一、已验证锚点（来自 `vm-replica/HANDOFF_NEXT_AGENT.md` 真机）

- 141（中文 Win11 教育版 26100.8521）：`ts_multifix` 内置偏移命中、多会话补丁施加/还原干净；
  `vm.create` 9s 上线第 3 路并发会话、`whoami` 正确、1280×800 截图成功、type 逐字命中；
  administrator console + zhou **全程 Active 不受影响**；`host.hibernate` 后 `footprint=zero`。
- 已归零的真实缺陷（离屏 RDP 长链路才暴露）：截图全黑/吞键、hold_key 只出 1 字符、首键被吞、
  多行 `\n`/`\t` 合并、冷启动 OOBE 夺焦、pythonw 无窗守护 `print()` 崩溃、Win11 开始菜单不吃 Esc（改用 Win 键）。
- **待补**：179 空白机从 0 装栈（relay 卡死待用户重启 ps-agent）；PyInstaller 单 exe 打包；闲时自动休眠计时验证；
  guacd → Webview 前端端到端（本 Runbook §八 的渲染层）。

---

## 十二、市面优质开源方案（选型持续调研 · 择优复用，不重造）

| 需求 | 候选（开源优先） | 采纳姿态 |
|---|---|---|
| 桌面版多会话 | `sebaxakerhtc/rdpwrap`(活跃 fork·ini 跟进) / 自研 `ts_multifix`(内存补丁+自发现) | 自研为主(可控/可 revert)，RDPWrap 作社区 ini 数据源与备选 |
| RDP→Web 渲染 | Apache Guacamole(guacd + common-js)、FreeRDP(WASM)、noVNC | Guacamole 首选(生态成熟/Webview 友好) |
| 内网穿透 | cloudflared + ntfy mesh(dao-bridge 已有) | 直接复用 |
| GPU 软件离屏 | IddCx 虚拟显示器驱动开源实现 | 增强档②，需管理员/重启 |
| 一键装机 | 自研冷启动安装器 + winget 拉工具链 | L1 路线 |

> 持续跟踪 GitHub 上「single-session→multi-session」「headless RDP」「guacamole vscode webview」类项目，
> 择其优纳入选型，避免重复造轮子。

---

*道法自然 · 无为而无不为 · 反者道之动 · 推进到底*
