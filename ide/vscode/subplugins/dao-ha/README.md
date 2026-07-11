# HA Copilot IDE (VS Code extension)

把整套 Home Assistant + `ha_copilot` 能力层桥接进 IDE —— 用户只需提供
**HA 地址 + 长效令牌** 这一最小输入，即可脱离浏览器，在 VS Code 内完成
对话、控制、配置编辑与 MCP 接入。

## 功能

| 板块 | 说明 |
|---|---|
| AI 对话 | Copilot 风格聊天视图：流式回复（▍光标）、工具调用卡片、■ 停止按钮、多轮会话，走 HA WebSocket + `ha_copilot_turn` 事件流 |
| 区域与实体 | 按区域分组的实体树，可开关实体（light/switch/input_boolean/…），实时状态 |
| 配置目录 | `hacfg://` 虚拟文件系统，直接在 IDE 编辑 HA `config/`（底层 `list_dir` / `read_config_file` / `write_config_file` 工具） |
| HA 面板 | 命令 `HA Copilot: 打开 Home Assistant 面板` 内嵌完整 `/ha-copilot` 面板 |
| MCP | 一键生成 `/api/ha_copilot/mcp/sse` 接入配置，任何 MCP 客户端即插即用 |
| run_tool | 快速选择并运行任意 ha_copilot 工具，结果以 JSON 文档展示 |

## 安装与连接

```bash
cd ide-extension
npx --yes @vscode/vsce package --no-dependencies
code --install-extension ha-copilot-ide-0.2.0.vsix
```

1. 命令面板 → `HA Copilot: 连接 Home Assistant (URL + Token)`
2. 输入 HA 地址（如 `http://127.0.0.1:8123`）和长效令牌
3. 侧边栏出现 HA Copilot 图标：AI 对话 + 区域与实体

适配任意安装形态（Docker / OS / Core / Supervised）——只要 HA 可达且装有
`ha_copilot` 集成即可获得全部功能。
