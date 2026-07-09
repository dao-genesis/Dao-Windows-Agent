# dao-proxy-pro (vendored slice)

真源: windsurf-assistant/plugins/dao-proxy-pro/vendor/外接api/core/sp_invert.js
（Proxy Pro 提示词隔离替换引擎 · 纯文本变换薄片, 不含 MITM/证书/LS 代理重器。）

勿手改 sp_invert.js（sync 时唯一改动: `_BUNDLED_DIR` 指向本目录 `bundled-origin/`,
经藏文本 `_silk_de/_silk_dao/_yinfu.txt` 一并 vendor）; 升级同步:

```bash
node ide/vscode/dao-proxy-pro/sync.js /path/to/windsurf-assistant
```

融合契约: 引擎读 `~/.dao/mode.json`（本仓 ModeManager 写入）——
coding 模式跳过道化(官方原貌), 其余模式经文后追加该模式 overlay。

同步时间: 2026-07-09T12:02:29.587Z
