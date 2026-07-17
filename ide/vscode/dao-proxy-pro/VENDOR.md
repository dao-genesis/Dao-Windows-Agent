# dao-proxy-pro (vendored slice)

真源: windsurf-assistant/plugins/dao-proxy-pro/vendor/外接api/core/sp_invert.js
（上游 plugins/ 布局已回归且含工具模式轴; sync.js 两套布局皆识别。
工具契约文本 _windows_agent/_freecad_agent/_kicad_agent.txt 一并 vendor。）
（Proxy Pro 提示词隔离替换引擎 · 纯文本变换薄片, 不含 MITM/证书/LS 代理重器。）

本仓补丁: 模式契约块（读 ~/.dao/mode.json）尚未回灌上游 —— 上游真源缺该补丁时
sync.js 会拒绝覆盖（防止静默丢失三插件融合枢纽）; 回灌上游后方可全量重同步。
当前基座已与上游 main 466b33e（含 R151 工具模式轴 TOOLMODE_MAP/getToolMode/setToolMode +
windows-agent 经藏）逐字一致, 仅多模式契约块（os 引入 / _currentModeState 块 /
invertSP·invertAnySP 的 _modeSkipsInvert+_modeOverlaySuffix / 导出 getModeState）。

勿手改 sp_invert.js（sync 时唯一改动: `_BUNDLED_DIR` 指向本目录 `bundled-origin/`,
经藏文本 `_silk_de/_silk_dao/_yinfu.txt` 一并 vendor）; 升级同步:

```bash
node ide/vscode/dao-proxy-pro/sync.js /path/to/windsurf-assistant
```

融合契约: 引擎读 `~/.dao/mode.json`（本仓 ModeManager 写入）——
coding 模式跳过道化(官方原貌), 其余模式经文后追加该模式 overlay。

同步时间: 2026-07-17T10:20:00Z（手工重同步 + 重打模式契约补丁）
