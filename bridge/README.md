# bridge · 机控守护进程落地位

> 复用 devin-remote 的成熟底座，不从零写。本目录是把机控能力接入本体系的落地点。

## 复用来源
- **devin-remote/cloud/vm-replica**：类虚拟机 host daemon + 每会话 inner agent（exec/file/screenshot/
  click/type/key/ui_tree），23 工具 MCP，端口路由，看门狗自愈。
- **devin-remote/addons/dao-bridge**：零配置内网穿透、`pc_*`(15) / `browser_*`(29·CDP) /
  `vscode_*`(8) / `plugin_*`(12) 四模块 MCP、UIAutomation 控件树 `pc_ui_tree`、窗口 `pc_activate`。

## 在本体系中的角色
- **级别①** 适配器（core/adapter/subprocess_api、cdp）本身在 session 内直接驱动软件，多数不需要 bridge。
- **级别②③** 适配器需要机控原语（截屏/输入/ui_tree/独立桌面），经 bridge 的 REST/MCP 落到：
  - 本 VM 的冷启动 Windows（coldstart/）— 开发验证靶机；
  - 或用户真机（经 DAO Bridge 隧道）— 生产。

## 暴露约定（沿用 vm-replica 结论：REST 内核 + MCP 外壳）
```
POST /api/session.create        -> {session_id}
POST /api/session.open_app      {session_id, app_id, ...}
POST /api/session.invoke        {session_id, app_id, verb, params}
POST /api/session.destroy       {session_id}
# 级别②③ 机控原语（落到目标隔离桌面/靶机）
POST /api/exec /api/file /api/screenshot /api/ui_tree /api/input /api/create_desktop ...
```
MCP 外壳把上述包装为工具，任意 Agent（Devin/Claude/本插件）即插即用。

> TODO（阶段2）：从 vm-replica vendor 机控 daemon 到此处 + 独立桌面/虚拟显示器 PoC（在 coldstart VM 内）。
