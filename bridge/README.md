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

## 已落地（阶段2·会话层 REST 内核 + MCP 外壳，纯标准库）

```
bridge/service.py   BridgeService：纯逻辑核心(dispatch 无 socket, 可离线单测)
bridge/server.py    REST 内核：python3 -m bridge.server --port 9930 [--token T]
bridge/mcp.py       MCP 外壳：python3 -m bridge.mcp  (JSON-RPC over stdio)
tests/test_bridge.py 单测(REST dispatch + MCP 往返)
```

### REST 路由（除 /api/health 外可选 Bearer token 鉴权）
```
GET  /api/health                                   -> {ok, apps, sessions}
GET  /api/apps                                     -> {apps}
POST /api/describe_app   {app_id}                  -> profile 详情(动词/参数/纪律)
POST /api/search_verbs   {query, limit?}           -> 跨软件动词检索
POST /api/session.create {session_id?}             -> {session_id, workdir}
GET  /api/session.list                             -> {sessions:[{session_id, apps}]}
POST /api/session.open_app {session_id, app_id}    -> {ok, ...}
POST /api/session.invoke   {session_id, app_id, verb, params?} -> {ok, value, error, logs}
POST /api/session.destroy  {session_id}            -> {ok, ...}
POST /api/session.prompt   {session_id}            -> 该会话应注入 Agent 的帛书系统提示
```

### MCP 工具（9 个·三段式发现→详述→执行，沿袭 ha-copilot 配方）
`list_apps · search_verbs · describe_app · session_create · session_list ·
session_open_app · session_invoke · session_destroy · session_prompt`

### 快速验证
```bash
python3 -m pytest tests/test_bridge.py -q
python3 -m bridge.server --port 9930 &            # REST
curl -s localhost:9930/api/health
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n' | python3 -m bridge.mcp   # MCP
```

> TODO（阶段3）：机控原语层——从 vm-replica vendor 机控 daemon 到此处
> (`/api/exec /api/file /api/screenshot /api/ui_tree /api/input /api/create_desktop`)
> + 独立桌面/虚拟显示器 PoC（在 coldstart Windows VM 内），级别②③ 适配器即接此层。
