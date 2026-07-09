# 子插件 spec（板块三 · 真实对接实例）

一份 spec = 一路真实子插件：`python3 -m bridge.subplugin_host --spec <spec.json>`
即起本地 `/invoke` 端点并向 `~/.dao/subplugins/` 写出描述符——主插件下次构建
registry 时自动收编为一路 @ 领域工作层（`core/subplugin.py`），与内置画像一视同仁。

| spec | 收编来源 | 说明 |
|---|---|---|
| `homeassistant.json` | ha-copilot/hactl | 智能家居：states / call_service / automation_create / check_config，全部经 hactl 底层 JSON 命令面。`HACTL` 环境变量可指向 `python3 <ha-copilot>/hactl/hactl.py`。 |

shell 模板里 `{param}` 为参数占位（值经 shlex.quote 注入）；字面 `${VAR}` 环境变量
写成 `${{VAR}}`（双大括号转义）。新增软件 = 落一份 spec，不改框架（樸散則為器）。
