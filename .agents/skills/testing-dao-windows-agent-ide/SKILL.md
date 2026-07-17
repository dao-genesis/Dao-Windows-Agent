---
name: testing-dao-windows-agent-ide
description: 在 Windows VM 的 Devin Desktop IDE 内实机验证 Dao-Windows-Agent 归一 VSIX（安装、登录、Windows 总控、机控桥 9930、模式切换）的流程与排坑。
---

# Dao-Windows-Agent 归一插件 · Devin Desktop（Windows）实机测试

## 安装与登录
- 打包：`"C:\Program Files\Git\bin\bash.exe" ide/vscode/build.sh` → `dao-windows-agent-0.1.0.vsix`（内部版本以 package.json 为准）。
- 安装：`C:\Users\<u>\AppData\Local\Programs\Devin\bin\devin-desktop.cmd --install-extension <vsix> --force`；扩展落在 `C:\Users\<u>\.devin\extensions\dao.dao-windows-agent-<ver>\`。
- 登录走浏览器 OAuth（Edge 首启会有 3-4 页向导，逐页点左下"不带数据继续"类按钮）。成功页弹「This site is trying to open Devin」→ 点 Open。账号见 Devin Secrets。
- **computer-use 打字丢 shift 字符**（@、大写、`>` 常被吞）：邮箱/密码/URL 一律 `Set-Clipboard` + Ctrl+V；命令面板用 Ctrl+Shift+P 后直接打小写关键词（勿手打 `>`）。

## 关键 UI 入口（VSIX 0.7.1 实测）
- 顶部 Agent/Editor 切换：测插件用 **Editor** 模式。
- `DAO: 归一主页（Windows 总控）` = daoWin.home（webview panel）；`DAO: 连接/自启机控桥` = daoWin.ensureBridge；`DAO: 切换模式`；`DAO · 提示词引擎: 状态`。
- **已知缺口**：`dao.unified` 归一统一面板（🪟 Windows 管理板块）与 `dao.proxyPro` 模式矩阵在本仓 VSIX 可能未接线（unified-panel.js/proxy-pro-panel.js 无人 require、views 未 contributes）——命令面板搜 "unified" 无结果即中招；真源接线在 windsurf-assistant/plugins/dao-desktop。
- daoWinHome 面板缓存旧桥状态：改桥后**关 tab 重开**才刷新。

## 机控桥（runtime, 端口 9930）
- Windows box 的 `C:\devin\python` 是 embedded Python（._pth 锁 sys.path），`python -m bridge.server` 必报 No module named 'bridge'，PYTHONPATH 无效。启动用：
  `python -c "import sys;sys.path.insert(0,r'<ext>\runtime');sys.argv=['bridge.server','--port','9930','--token','dao-win-lab'];import bridge.server as s;s.main()"`
- 探活：`curl http://127.0.0.1:9930/api/health` → `{"ok":true,"apps":[...]}`。
- 坑：默认 9920 可能被 Devin.exe 内 dao-freecad-shell 占用且 /api/health 也回 ok:true → 把 `daoWin.bridgeUrl` 设为 9930 再点「DAO: 连接/自启机控桥」（toast「DAO 桥已连」为准）。
- 模式切换真源：`~/.dao/mode.json`（mode/tool_policy/overlay），切换后 shell 读它断言持久化。

## Devin Secrets Needed
- Devin Desktop 登录账号/密码（outlook 账号）

## 其他
- upload_attachment 工具不认 Windows 盘符路径：文件先拷到 `C:\tmp\`（对应 /tmp），用 `/tmp/...` 路径上传。
- 录屏前最大化 IDE 窗口（双击标题栏或点最大化钮；勿用 Super+Up）。
