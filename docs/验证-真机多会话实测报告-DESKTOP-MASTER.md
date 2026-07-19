# 验证报告 · 真机多会话实测（DESKTOP-MASTER）

> 日期：2026-07-19 ｜ 通道：DAO Bridge 持久化中继（脱离 IDE）｜ 全程只读探测 + 一次可逆多会话实测
> 结论：**Windows 多 RDP「一窗一路独立桌面」通用基底在真机上端到端跑通、可逆、主控制台零影响。**

道法自然 · 无为而无不为。本报告固化了本源目标——「装上插件即完美接入用户电脑、道并行不相背」——
在一台**已配置**家用真机上的实测证据，作为 `core/session_activator.py`、`core/desktop_router.py`
与兜底 Runbook 的**事实锚点**。

---

## 一、被测机环境（只读探测）

| 项 | 值 | 对多会话的意义 |
|---|---|---|
| 版本 | Windows 11 教育版（SKU 121） | 原生含 RDP host（等同 Pro/Ent），非 Home |
| 内部版本 | Build 26200 | 新版内核 |
| 权限 | Administrator（`is_admin=true`） | 可配置 RDP/账号/服务 |
| RDP 开关 | `fDenyTSConnections=0`（已开） | 允许入站 RDP |
| 单会话限制 | `fSingleSessionPerUser=0`（已放开） | **允许同账号多会话** |
| TermService | Running · Automatic | RDP 服务常驻 |
| RDPWrap | 已装且**已注入**（`rdpwrap.dll` 在 svchost 模块表） | 桌面版多并发会话的关键 |
| RDPWrap ini | 含当前 `termsrv.dll` 版本条目（`ini_has_version=true`） | 补丁与内核版本匹配、生效 |
| termsrv 版本 | 10.0.26100.8115 | 与 ini 对齐 |
| NLA | `UserAuthentication=0`（关） | 便于免交互/回环直登 |
| 3389 监听 | 是 | 监听器就绪 |

**已就绪的多路账号 + 回环路由 + 凭据入库**（用户此前配好，正是本源架构所需形态）：

| 账号 | 回环地址 | 凭据管理器 | 桌面 .rdp |
|---|---|---|---|
| Administrator | 127.0.0.1 / .20 | 已存 | — |
| zhouyoukang | 127.0.0.2 | 已存 | — |
| zhou | 127.0.0.3 | 已存 | RDP_zhou.rdp |
| zhou1 | 127.0.0.4 | 已存 | RDP_zhou1.rdp |
| zhou2 | 127.0.0.5 | 已存 | RDP_zhou2.rdp |
| daovm | 127.0.0.6 / .9 | 已存 | RDP_daovm.rdp |
| daotest | 127.0.0.7 | 已存 | RDP_daotest.rdp |
| ai | 127.0.0.8 | 已存 | RDP_ai.rdp |

`RDP_zhou.rdp` 关键字段（正是免提示直登的标准形态）：
```
full address:s:127.0.0.3
username:s:zhou
authentication level:i:0
prompt for credentials on client:i:0
negotiate security layer:i:0
enablecredsspsupport:i:0
```

---

## 二、多会话实测（一次·可逆）

初态 `qwinsta`：仅主控制台在线。
```
>console        Administrator   1  Active
 rdp-tcp                    65536  Listen
```

**激活一路并发会话**（账号 `ai`，凭据已入库，回环 127.0.0.8）：
```
mstsc /v:127.0.0.8      # 免提示直登
```
8s 后 `qwinsta`：
```
>console        Administrator   1  Active     ← 主控制台不受影响
 rdp-tcp#0      ai              4  Active     ← 新并发会话 Active
 rdp-tcp                    65536  Listen
```

**新会话是完整桌面**（并非空壳）：`ai` 用户下 **52 个进程**，含独立 `explorer`、
中文输入法、SearchHost、Widgets、Edge WebView、第三方常驻（Logitech/HP/NVIDIA）等；
全机 `explorer` 实例数 = 2（主控制台一份 + ai 一份），互不干扰。

**可逆回收**：
```
logoff 4
```
回到初态（仅主控制台 + 监听器），无残留会话。

---

## 三、结论与固化

1. **基底成立**：桌面版（教育版）经 RDPWrap + 放开单会话 + 回环多路 + 凭据入库，
   可**程序化**拉起任意账号的独立 Active 桌面，主控制台与既有会话零影响，且**可逆**。
2. **最短可信链路**已固化进 `core/session_activator.py`：
   `store_credential`(cmdkey 入库) → `activate`(mstsc 回环拉起) → `list_sessions`(qwinsta 枚举) →
   `logoff`/`logoff_user`(可逆回收)。均经可注入 runner，Linux/CI 纯逻辑可单测（本次真机样本已进单测）。
3. **与既有编排对齐**：`DesktopRouter` 的「一窗一路」在此机判定为路 A（多会话 RDP）；
   本层补齐「把账号点亮成活桌面」的最后一跳，供隧道/guacd 建 RDP→WS→面板链路。

## 四、边界与下一步（诚实）

- 本机为**已配置**样本：RDP/RDPWrap/账号/凭据均已就位。**未配置的家用机（尤其 Home 版无 RDP host）**
  仍需按兜底 Runbook 逐档、知情同意、可回滚地配备；Home 版多真会话需 RDPWrap（第三方·供应链风险），
  或退虚拟显示器/无头/coldstart。
- 跨会话 GUI 操作（在非当前会话内截图/注入输入）此前已在 vm-replica 验证；
  下一步将其与 `SessionActivator` 合流，形成「激活→渲染→操作→回收」闭环，并逐步降 AI 参与度（L3→L0）。
- 本次仅对被测机做了**一次可逆多会话实测**，未改动任何全局策略、未新建/删除账号、未触碰用户既有会话。

*道法自然 · 无为而无不为*
