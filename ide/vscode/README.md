# DAO Windows Agent · IDE 前端 = 归一插件(dao-one)衍生

> **本源唯一**：本目录**不自建任何插件前端**。IDE 交付 = **dao-one(devin-remote 真源·归一插件)**
> 经 [`dao-one-windows/`](dao-one-windows/) 衍生注入器折入 **🪟 Windows 板块** 后打包的 VSIX。
> Windows 是 dao-one 全能板(9920)中与 切号/穿透/Proxy/备份/GitHub 同级的一个 tab，
> 不是独立产品、不是第二套面板、不是新架构。

## 隔离的唯一含义

与 Devin Desktop 内**在研**的 dao-one 只做**开发流与安装态**分离（分宿主并存、互不干扰·
鸡犬相闻，民至老死不相往来）；**底层同一**（道并行而不相悖），绝不另建产品架构。

## 构建

```bash
bash build.sh
# ① 取/更新 devin-remote 真源(DAO_UPSTREAM 可指向本地检出, 缺省浅克隆到 .upstream/)
# ② cd core/dao-one && npm install && node build.js  —— 真源自己的装配(vendor-*)
# ③ node dao-one-windows/inject.js <dao-one> .stage/dao-one-win  —— 锚点折入 🪟 板块
# ④ 收敛运行时形态(剔除构建器/开发依赖) → pack_vsix.py → dao-one-windows-<版本>.vsix
```

## 🪟 Windows 板块内容（全部在注入负载 [`dao-one-windows/payloads.js`](dao-one-windows/payloads.js)）

- **官方 mstsc 五页配置台**：常规/显示/本地资源/体验/高级，逐键映射官方 `.rdp` 语义，`.json`+`.rdp` 落盘；
- **Windows 账号池**：多账号创建/开桌面/销毁（注册表专用 `win-guac-accounts.json`，绝不碰 Devin 登录态）；
- **同源桌面路由**：主口 `/wdesk/*` → guacamole-lite 隧道(HTTP 4824 / WS 4823) → guacd → RDP 3389，
  一账号一页、并行多桌面会话。

## 长驻

`dao-one-windows/reinject.js`（计划任务）：dao-vsix 自更新覆盖 vendor 后自动检测「未注入/已注入/过时」，
从 `.prewin` 真源幂等重折入，重启/自更新不丢板块。

## 自检

```bash
node --test test/            # 注入器护栏(锚点契约/负载/.rdp 键/幂等/架构护栏)
python3 -m pytest ../../tests -q
```
