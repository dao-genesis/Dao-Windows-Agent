# DAO Windows Agent · VSCode 前端

把整台 Windows 做进 IDE：**每个 IDE 窗口 = 一个单账号零配置隔离会话**（类多RDP效果，与用户真实桌面并行、互不干扰）。插件不投屏，而是经机控桥（`bridge/` REST）直达级别①②③。

## 本源
- 打开一个 VSCode 窗口，插件即为其分配一个稳定的隔离会话（`ide_<hash>`，绑定工作区路径）。
- 面板里的动作全部落到机控桥的 `/api/*`：级别①（system profile 无头 exec/file/proc）、级别②（notepad 隔离桌面 round-trip）、级别③（PrintWindow 截图取证）。
- N 个 IDE 窗口 = N 个互不干扰实例，无需建账号、无需 RDPWrap、零配置。

## 冷启动（零配置）
1. 插件激活即尝试连 `daoWin.bridgeUrl`（默认 `http://127.0.0.1:9920`）。
2. 连不上且 `daoWin.autostart=true` 时，用插件**自带的 `runtime/`（打包时捆入的 `bridge/`+`core/`）**以 `daoWin.pythonPath` 起一个本地桥（端口 9930），无需任何手工部署。

## 打包
```bash
bash build.sh   # 捆入 runtime + vsce package → dao-windows-agent-0.1.0.vsix
```

## 安装
在 VSCode 里：扩展面板 → `...` → 从 VSIX 安装 → 选 `dao-windows-agent-0.1.0.vsix`。
或命令行：`code --install-extension dao-windows-agent-0.1.0.vsix`。

## 配置项
| 键 | 默认 | 说明 |
|---|---|---|
| `daoWin.bridgeUrl` | `http://127.0.0.1:9920` | 机控桥地址 |
| `daoWin.token` | `dao-win-lab` | Bearer token（与桥 `--token`/`DAO_WIN_TOKEN` 一致） |
| `daoWin.autostart` | `true` | 连不上时用自带 runtime 起本地桥 |
| `daoWin.pythonPath` | `python` | 自启桥所用 Python |
