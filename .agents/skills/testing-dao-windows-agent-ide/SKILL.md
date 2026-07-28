---
name: testing-dao-windows-agent-ide
description: 在真机(zhoumac)的 VS Code/Devin Desktop 内实机验证 dao-one 衍生 VSIX（dao-one-windows：归一全能板 + 🪟 Windows 板块、mstsc 五页 RDP、账号池、同源桌面路由）的流程与排坑。
---

# Dao-Windows-Agent · dao-one 衍生 VSIX 实机测试

## 交付形态（本源）
- 交付 = **dao-one(devin-remote 真源) + dao-one-windows 注入器折入 🪟 Windows 板块**，
  打包为 `ide/vscode/dao-one-windows-<版本>.vsix`（扩展 id 仍为 `dao.dao-one`，版本号在真源上 +1 patch）。
- 构建：`bash ide/vscode/build.sh`（可 `DAO_UPSTREAM=<本地 devin-remote 检出>` 免克隆；产物在 ide/vscode/ 下）。
- **无独立主页/无 dao.unified/无 daoWin.* 命令**——那是已退役的漂移产物。全部 UI 在 dao-one 的
  9920 全能板内：🪟 是与 切号/穿透/Proxy/备份/GitHub 同级的 tab。

## 安装与并存
- 安装：`code --install-extension <vsix> --force` 或 Devin Desktop 的 `devin-desktop.cmd --install-extension <vsix>`。
- 与 Devin Desktop 内在研 dao-one 并存 = 分宿主（`~/.vscode/extensions` vs `~/.devin/extensions`），
  同 id 同宿主会互相覆盖——测试装到与在研版不同的宿主。
- dao-vsix 自更新会抹掉注入——`dao-one-windows/reinject.js`（计划任务）负责幂等重折入；
  测试时若板块消失，先跑 reinject 再重载窗口。
- 新开 VS Code 窗口加 `--disable-workspace-trust`，否则扩展可能被禁用。

## 验证要点
- 打开 dao-one 全能板（端口 9920/9921...），侧栏出现 🪟 tab；点入 = Windows 板块。
- RDP：列表/新建/编辑（官方 mstsc 五页）/保存/另存/取消/顶部返回；`.json`+`.rdp` 落盘于工作区。
- 账号池：创建/开桌面/销毁；注册表在 `win-guac-accounts.json`，**绝不写 Devin ~/.dao/accounts.json**。
- 桌面路由：`/wdesk/*`（HTTP 4824）与 `/wdesk-ws`（WS 4823）同源转发到 guacamole-lite → guacd → RDP 3389；
  一账号一页、并行多桌面互不串台。
- 机控桥 9930（repo 根 bridge/，独立进程，不再捆入 VSIX）：`curl http://127.0.0.1:9930/api/health`。

## 真机排坑（zhoumac 实测）
- computer-use 打字丢 shift 字符（@、大写、`>` 常被吞）：一律 `Set-Clipboard` + Ctrl+V。
- 远端 IME 会改写面板内直接键入的文本（连接名等）——用剪贴板粘贴。
- embedded Python（`._pth` 锁 sys.path）跑桥须 `python -c "import sys;sys.path.insert(0,r'<repo>');...from bridge.server import main"`，`-m bridge.server` 必败。
- webview 面板缓存旧状态：改配置后关 tab 重开。
