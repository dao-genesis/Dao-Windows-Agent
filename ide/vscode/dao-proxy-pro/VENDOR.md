# dao-proxy-pro (vendored slice)

真源: windsurf-assistant/packages/dao-proxy-pro/vendor/外接api/core/sp_invert.js
（上游 plugins/dao-proxy-pro 已重构不再含 sp_invert; packages/ 为其自同步的发布快照。
经藏文本随迁至 packages/dao-proxy-min/vendor/bundled-origin。sync.js 两套布局皆识别。）
（Proxy Pro 提示词隔离替换引擎 · 纯文本变换薄片, 不含 MITM/证书/LS 代理重器。）

本仓补丁: 模式契约块（读 ~/.dao/mode.json）尚未回灌上游 —— 上游真源缺该补丁时
sync.js 会拒绝覆盖（防止静默丢失三插件融合枢纽）; 回灌上游后方可全量重同步。
当前基座已与 packages 快照(9.9.347)逐字一致, 仅多模式契约块。

勿手改 sp_invert.js（sync 时唯一改动: `_BUNDLED_DIR` 指向本目录 `bundled-origin/`,
经藏文本 `_silk_de/_silk_dao/_yinfu.txt` 一并 vendor）; 升级同步:

```bash
node ide/vscode/dao-proxy-pro/sync.js /path/to/windsurf-assistant
```

融合契约: 引擎读 `~/.dao/mode.json`（本仓 ModeManager 写入）——
coding 模式跳过道化(官方原貌), 其余模式经文后追加该模式 overlay。

同步时间: 2026-07-09T12:02:29.587Z
