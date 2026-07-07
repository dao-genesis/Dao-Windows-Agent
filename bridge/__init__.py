"""机控桥：把 core/ 的类虚拟机会话与应用适配层，经 REST(内核) + MCP(外壳) 暴露。

设计要点（道法自然 · 无为而无不为）：
- 纯标准库，无第三方依赖——级别① 在纯 Linux 即可跑通，冷启动 VM/真机才需机控原语。
- 核心是纯函数式 dispatch（BridgeService.dispatch），不依赖 socket，便于离线单测。
- server.py 是 http.server 薄壳；mcp.py 是 JSON-RPC over stdio 薄壳；二者共用同一 service。
"""
from bridge.service import BridgeService

__all__ = ["BridgeService"]
