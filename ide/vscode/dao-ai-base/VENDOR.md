# dao-ai-base (vendored)

真源: windsurf-assistant/plugins/dao-desktop (dao-cascade + windsurf-shim) 及 plugins/dao-ai-base/index.js。
请勿在此处直接改核心; 改真源后用同步脚本重新 vendor:

    node plugins/dao-ai-base/sync.js <本插件目录>

同步时间: 2026-07-11T14:05:59.077Z

本仓补丁: dao-cascade/panel.js 回植领域提示词塑形器钩子 setPromptShaper/_shapeText/mode-toggle
(上游本源校正版重写时脱落; 四领域插件的提示词隔离/替换依赖此融合点, 待回灌上游真源)。
