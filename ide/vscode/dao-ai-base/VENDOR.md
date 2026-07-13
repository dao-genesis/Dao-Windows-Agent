# dao-ai-base (vendored)

真源: windsurf-assistant/plugins/dao-desktop (dao-cascade + windsurf-shim) 及 plugins/dao-ai-base/index.js。
请勿在此处直接改核心; 改真源后用同步脚本重新 vendor:

    node plugins/dao-ai-base/sync.js <本插件目录>

同步时间: 2026-07-13T14:30:00Z（上游 R68·19c96eb：acp-client onExit+SIGTERM→SIGKILL 杀净、panel _ensureAcp 单飞+退避+authenticate(windsurf-api-key) 补鉴权 —— R67 孤儿进程 OOM 根因修复与 R68 Devin Local ACP 鉴权均已并入）

本仓补丁: dao-cascade/panel.js 回植领域提示词塑形器钩子(setPromptShaper/_shapeText/mode-status/daoModePill/exports)——上游真源尚缺此钩子, 每次重新 vendor 后须重打(待回灌上游真源)。
