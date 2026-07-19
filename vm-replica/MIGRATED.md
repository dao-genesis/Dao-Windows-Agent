# 迁入说明 · 正本清源归位

本目录（`vm-replica/`）原在 **`dao-genesis/devin-remote` 的 `cloud/vm-replica/`**。

## 为什么迁

devin-remote 的本源职责是**归一插件（dao-one = dao-vsix 二合一 + Proxy Pro + rt-flow + dao-bridge）**，
不应承载 Windows Agent 的延伸开发。多 RDP / 复制品桌面 / 类虚拟机骨架 / 视觉 grounding 调研属于
**Windows Agent 项目**，故整体归位本仓（`dao-genesis/Dao-Windows-Agent`）。

对应的 devin-remote 清理见其 PR：剥离 dao-one 的 `windows-fold.patch` 折叠与 vm-replica 捆绑、
删除 `cloud/vm-replica/`。

## 迁入范围

- `agent-vm/`：宿主守护 `vm_host_daemon.py` / 会话内代理 `vm_inner_agent.py` / MCP 服务
  `mcp_server.py`·`mcp_http.py` / 部署 `deploy_host.py` / `vmctl.py`·`vmodel.py`·`uia.py`·`ts_multifix.py`
  以及视觉 grounding 调研模块（`flow_*` / `motion_*` / `occlusion*` / `region_parse` / `temporal_*`
  / `multiregion` 等）与其单测。
- `rdp-web/`：node-rdpjs 官方 RDP 线协议网关 + mstsc.js webclient（**路线 A 的一种后端实现**，
  与本仓 `desktop/` 的 Guacamole 路线并列，供选型/参考）。
- `vendor/`：第三方 MCP 源登记。
- `01_*.md … 09_*.md` / `README.md` / `HANDOFF_*.md`：调研与交接归档。

## 未迁入（有意）

- `agentctl/`：已独立自研并归入本仓 `core/gui/agentctl/`，不重复。
- `archive_practice/`：devin-remote 账号相关的一次性脚本与实测截图证据，git 历史已留存，不带入。

## 与本仓既有实现的关系

本仓已有更贴合「装上插件即接入用户电脑」本源的实现：`desktop/`（Guacamole 路线 A）、
`coldstart/`（QEMU/KVM 路线 Z）、`core/adapter/`（控制面）、`core/environment.py`（任意环境探测/选路）。
本目录作为**调研成果与备选后端**保留，后续按「桌面级路由本源」择优收编，不强制并入主链路。
