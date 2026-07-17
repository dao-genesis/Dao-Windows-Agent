# dao-ai-base (vendored)

真源: windsurf-assistant/plugins/dao-desktop (dao-cascade + windsurf-shim) 及 plugins/dao-ai-base/index.js。
请勿在此处直接改核心; 改真源后用同步脚本重新 vendor:

    node plugins/dao-ai-base/sync.js <本插件目录>

同步时间: 2026-07-17T16:40:00Z（mode-fusion.js + proxy-pro-panel.js 部分重同步）
同步基线: 上游 466b33e（R151）; mode-fusion.js/proxy-pro-panel.js 已随上游 R154 4×4 模式轴重同步
（提示词层 官方/道德经/阴符经/二经合 × 工具层 默认/Windows/FreeCAD/KiCad, 详见上游 PR #89）

本仓补丁(上游真源尚缺, 每次重新 vendor 后须重打, 待回灌上游):
- dao-cascade/panel.js: 领域提示词塑形器钩子(setPromptShaper/_shapeText/mode-status/daoModePill/exports)
- dao-cascade/ls-bridge.js: apiKeyCandidates TTL 缓存 + invalidateKeyCache(state.vscdb 重活防阻塞)
- dao-cascade/host-discover.js: win32 短路 / 先廉后贵 / 轮询退避(保留本仓版, 未取上游)
- dao-cascade/host-state.js: hostFire 重入护栏 + publishFused 不动点(保留本仓版, 未取上游)
- index.js: 宿主接线 dao.unified 归一面板 + dao.proxyPro 独立面板(②b/②c, 与真源 dao-desktop/extension.js 同构; 视图声明落宿主 package.json daoWin-cascade 容器)
- dao-cascade/unified-panel.js: 主页复位归一总览(Windows 只留环境卡) + 🪟 Windows 子板块收编官方 mstsc 五页 RDP 配置/子板块管理(win-rdp-*/win-sub-toggle/win-reveal-dir, 原语经宿主 extension.js __DAO_WIN_HOME__ 上交, 单页统管不另起独立主页)
