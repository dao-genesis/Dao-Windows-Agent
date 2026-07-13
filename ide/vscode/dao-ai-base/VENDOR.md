# dao-ai-base (vendored)

真源: windsurf-assistant/plugins/dao-desktop (dao-cascade + windsurf-shim) 及 plugins/dao-ai-base/index.js。
请勿在此处直接改核心; 改真源后用同步脚本重新 vendor:

    node plugins/dao-ai-base/sync.js <本插件目录>

同步时间: 2026-07-13T08:27:29.076Z

本仓补丁: dao-cascade/panel.js 回植领域提示词塑形器钩子(setPromptShaper/_shapeText/mode-status/daoModePill/exports)——上游真源尚缺此钩子, 每次重新 vendor 后须重打(待回灌上游真源)。
