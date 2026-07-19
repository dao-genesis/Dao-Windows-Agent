# 验证 · 多路并发会话闭环实测 — DESKTOP-MASTER

> 道法自然 · 无为而无不为。本报告记录在真机 DESKTOP-MASTER 上，经 DAO Bridge 内网穿透
> 远程验证「回环目标发现 → 多路激活 → 并发 Active → 会话隔离 → 逐路可逆回收」的完整闭环。
> 对应 PR：`feat(rdp-target)` 合流闭环 + `fix(rdp-target)` 同名多回环修复。

## 环境

| 项 | 值 |
|---|---|
| 主机 | DESKTOP-MASTER |
| 接入 | DAO Bridge 快速隧道（CloudFlare·轮换） |
| 插件桥版本 | dao-bridge 3.7.1 |
| 探测/激活/回收路径 | `/api/exec`（等价 SessionActivator 的 cmdkey/mstsc/qwinsta/logoff 序列） |

## 一 · 只读目标发现（验证 `RdpTargetRegistry`）

真机桌面 `.rdp` 文件解析结果：

| 文件 | 回环地址 | 账号 |
|---|---|---|
| Kiro.rdp | 127.0.0.2 | zhou1 |
| RDP_zhou.rdp | 127.0.0.3 | zhou |
| RDP_zhou1.rdp | 127.0.0.4 | zhou1 |
| RDP_zhou2.rdp | 127.0.0.5 | zhou2 |
| RDP_daovm.rdp | 127.0.0.6 | daovm |
| RDP_daotest.rdp | 127.0.0.7 | daotest |
| RDP_ai.rdp | 127.0.0.8 | ai |
| 笔记本.rdp | 192.168.31.179 | zhouyoukang |

`笔记本.rdp` 是 LAN 目标（非回环），发现逻辑**正确排除**，不纳入回环分配。

`cmdkey /list` 真机格式为 `Target: Domain:target=TERMSRV/127.0.0.x`（带 `Domain:target=` 前缀），
解析器以 `.search` 命中，兼容。真机凭据含回环 .1–.9 与 .20。

**发现一处真机才暴露的缺陷并已修复**：Administrator 同时持有 127.0.0.1 与 127.0.0.20 两路回环，
早先按 username 合并会丢掉 .20 → 可能误分配已占用地址。已改为**按回环 IP 主键合并**（一 IP 一目标），
并补回归测试 `test_discover_keeps_multiple_loopbacks_for_same_user`。

## 二 · 单路激活 → Active → 回收（闭环）

```
基线:       >console  Administrator  1  Active   （仅控制台）
激活:       mstsc /v:127.0.0.8
结果:       rdp-tcp#0  ai  5  Active   （console 1 仍 Active）
完整桌面:   session 5 进程 53 个, 含 explorer
回收:       logoff 5
结果:       回到 >console 1 Active + listener（干净）
```

## 三 · 多路并发（本次核心）

```
激活:       mstsc /v:127.0.0.8 ; mstsc /v:127.0.0.3
结果:       >console      Administrator  1  Active
            rdp-tcp#0     ai             6  Active
            rdp-tcp#1     zhou           7  Active
```

**三路会话同时 Active**：控制台 + ai + zhou，全程互不影响。

### 会话隔离实证

| 会话 | 进程数 | explorer | explorer PID |
|---|---|---|---|
| session 6 (ai) | 49 | 是 | 49280 |
| session 7 (zhou) | 53 | 是 | 48396 |

两路各自拥有**独立的 explorer.exe（PID 互异）与独立进程树** → 桌面态天然隔离，互不串扰。

### 逐路可逆回收

```
回收:       logoff 6 ; logoff 7
结果:       回到 >console  Administrator  1  Active + listener
```

控制台 Administrator 会话**全程 Active、零影响**；两路被建会话干净回收，无残留。

## 四 · 结论与边界

- 「发现→多路激活→并发 Active→隔离→逐路回收」在真机 DESKTOP-MASTER 完整闭环，可逆、控制台无损。
- 本机为已配置多会话（RDPWrap 已载、`.rdp`/凭据齐备）的 Win11 教育版；对未配置的
  Home/未开 RDP 的 Pro/域机/无管理员环境，仍需先经 `EnvironmentManager.provision`（知情同意·可回滚）
  或退兜底 Runbook。
- 下一步：把激活后的一路 Active 桌面接入 guacd→WS→归一面板渲染，做 GUI 输入/截图代操作的隔离验证。

## 五 · 渲染链路真机联调（guacd/WS 摄取 + 输入注入）

把 `vm-replica/rdp-web` 渲染栈（gateway + node-rdpjs + `render_probe.js` 无头探针）经 DAO Bridge
分块推送到台式机（403 文件，`node --check` 通过），用探针复用 gateway 的 RDP 摄取路径无头连接
已激活的回环会话，统计真实位图帧并注入一次指针/键盘事件。**全程只连目标回环，不碰控制台。**

### 单路渲染 + 输入注入

为避免读取真实用户口令，创建可回收测试账号 `daorender`（口令仅存本会话内存·不落库/不入 PR），
分配 `127.0.0.10`，探针连接：

```json
{"ok":true,"connected":true,"frames":1484,"bytes":13427112,"firstFrameMs":1251,"injected":true,
 "target":"127.0.0.10","user":"daorender"}
```

- **1484 帧真实位图**（约 13MB 桌面像素），首帧 1.25s → RDP→位图流渲染链路真机产出帧。
- `injected:true` → 指针+键盘事件成功注入目标会话。
- `qwinsta` 确认：`daorender`(ID 8) 自有会话，`Administrator` console(ID 1) 全程 Active，
  帧与输入只作用于 session 8，控制台未受影响。

### 双路并发渲染（PR #92 按账号多路的直接验证）

再建 `daorender2`@`127.0.0.11`，两个探针并发：

| 路 | 账号 | 目标 | 帧数 | 字节 | injected |
|---|---|---|---|---|---|
| 1 | daorender | 127.0.0.10 | 792 | 3,094,406 | 是 |
| 2 | daorender2 | 127.0.0.11 | 1415 | 12,582,935 | 是 |

并发中 `qwinsta`：

```
>console      Administrator  1   Active
 rdp-tcp#0    daorender      8   Active
 rdp-tcp#1    daorender2    10   Active
```

**两路独立 RDP 渲染流同时产帧**，各连自己的账号/回环目标，控制台保持 Active。

### 可逆回收

`logoff 8;10` → `cmdkey /delete` 两条 → `net user daorender/daorender2 /delete` → `qwinsta`
回到 **console-only + listener**，控制台 Active 无损。推送的临时 b64/zip 与探针输出已清理，
本机与远端均无口令残留。

### 边界（诚实）

- 本次验证的是「RDP→位图帧摄取 + 输入注入 + 会话隔离 + 多路并发」，即 gateway 渲染链路的**服务端摄取**已在真机跑通。
- 「WS→浏览器 canvas→归一面板」的前端可视化联调仍走 `webclient` + IDE 面板，属前端集成，未在本报告覆盖。

*道法自然 · 无为而无不为*
