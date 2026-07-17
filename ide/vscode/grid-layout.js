"use strict";
// 道 · 多实例桌面网格布局核（纯函数·零依赖·可单测）。
// ─────────────────────────────────────────────────────────────────────────────
// 本源：把多路 Windows 分身桌面「塞进一个网页内」同时呈现与调度——不再是一次只见一路的
// 标签页(tabs)，而是平铺网格(grid)里每路分身各占一格、画面皆活、点谁谁得输入焦点。
// desktopHtml 的 webview 脚本无法 require 模块，故这里作唯一真源，经 .toString() 内联进模板，
// 单测与实机同一份实现，杜绝漂移。

// 依分身数算网格行列：近似正方（cols=ceil(√n)），行数补足；空态按 1×1。
function gridDims(n) {
  const count = Math.max(0, Math.floor(Number(n) || 0));
  if (count <= 1) return { cols: 1, rows: 1 };
  const cols = Math.ceil(Math.sqrt(count));
  const rows = Math.ceil(count / cols);
  return { cols, rows };
}

module.exports = { gridDims };
