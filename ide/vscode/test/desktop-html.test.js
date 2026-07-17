"use strict";
// 桌面路由面板 webview 模板 headless 单测：
// 1) 生成的内联脚本必须语法完好（真机踩坑：模板字面量吞 \/ 令整段脚本 SyntaxError 报废）;
// 2) 平铺网格调度要素（gridDims/toggleLayout/applyLayout/grid CSS）必须在产物内。
const { test } = require("node:test");
const assert = require("node:assert");
const Module = require("module");

// vscode 模块桩：extension.js 顶层 require("vscode")，headless 下以最小桩顶替。
const fakeVscode = {
  Uri: { joinPath: () => ({ toString: () => "vscode-resource://media" }) },
  workspace: { getConfiguration: () => ({ get: () => undefined }) },
};
const origLoad = Module._load;
Module._load = function (request) {
  if (request === "vscode") return fakeVscode;
  return origLoad.apply(this, arguments);
};
const { desktopHtml } = require("../extension");
Module._load = origLoad;

const fakeWebview = {
  cspSource: "vscode-resource:",
  asWebviewUri: (u) => u,
};

function renderHtml() {
  return desktopHtml(
    fakeWebview,
    { extensionUri: {} },
    "ide_testhash",
    "dao",
    "http://127.0.0.1:4824",
    4823,
    [{ name: "dao" }, { name: "dao2" }],
    "test-token"
  );
}

test("webview 内联脚本语法完好（可被解析）", () => {
  const html = renderHtml();
  const m = html.match(/<script>([\s\S]*)<\/script>/);
  assert.ok(m, "应含内联脚本");
  assert.doesNotThrow(() => new Function(m[1]), "内联脚本必须无语法错误");
});

test("平铺网格调度要素齐备", () => {
  const html = renderHtml();
  for (const needle of [
    "function gridDims",
    "function toggleLayout",
    "function applyLayout",
    "function fitAll",
    "#desktop.grid",
    'id="layoutBtn"',
  ]) {
    assert.ok(html.includes(needle), "缺: " + needle);
  }
});

test("布局态随分身布局一并持久化（webview 重载后复归）", () => {
  const html = renderHtml();
  assert.ok(html.includes("layout: layout"), "saveLayout 应含 layout");
  assert.ok(html.includes("st.layout === 'grid'"), "boot 应复归 layout");
});
