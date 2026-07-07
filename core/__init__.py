"""Dao-Windows-Agent · 通用应用适配层核心。

把整个 Windows 电脑做进 IDE 插件，达到多实例类虚拟机效果：
- 每个 IDE 窗口 = 一个 session（类虚拟机实例），绑定一组软件实例；
- 软件驱动分三级降级：① app 原生 API/CLI/CDP（无头·天然隔离·首选）
  ② 隔离桌面(CreateDesktop/虚拟显示器)+UIA  ③ 视觉 grounding 兜底；
- 新增软件 = 写一个薄片 profile，不重造框架（樸散則為器）。

道法自然 · 无为而无不为。
"""

__version__ = "0.1.0"
