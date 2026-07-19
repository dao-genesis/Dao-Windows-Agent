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

*道法自然 · 无为而无不为*
