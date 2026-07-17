// 归一面板宿主接线护栏：回灌的 unified-panel / proxy-pro-panel 必须真正接进宿主
// （package.json 视图声明 + dao-ai-base 激活链 require），防止 vendor 只带文件不带接线。
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));

test("package.json 声明 dao.unified / dao.proxyPro webview 视图", () => {
  const views = (pkg.contributes.views || {})["daoWin-cascade"] || [];
  for (const id of ["dao.unified", "dao.proxyPro"]) {
    const v = views.find((x) => x.id === id);
    assert.ok(v && v.type === "webview", id + " 应为 daoWin-cascade 容器内 webview 视图");
  }
  assert.ok(
    (pkg.contributes.commands || []).some((c) => c.command === "dao.unified.open"),
    "命令面板应可达 dao.unified.open"
  );
});

test("dao-ai-base 激活链接线 unified-panel 与 proxy-pro-panel", () => {
  const idx = fs.readFileSync(path.join(ROOT, "dao-ai-base", "index.js"), "utf8");
  assert.ok(idx.includes('require("./dao-cascade/unified-panel")'), "index.js 应 require unified-panel");
  assert.ok(idx.includes('require("./dao-cascade/proxy-pro-panel")'), "index.js 应 require proxy-pro-panel");
  const uni = fs.readFileSync(path.join(ROOT, "dao-ai-base", "dao-cascade", "unified-panel.js"), "utf8");
  assert.ok(uni.includes('registerWebviewViewProvider("dao.unified"'), "unified-panel 应注册 dao.unified");
  const px = fs.readFileSync(path.join(ROOT, "dao-ai-base", "dao-cascade", "proxy-pro-panel.js"), "utf8");
  assert.ok(px.includes('registerWebviewViewProvider("dao.proxyPro"'), "proxy-pro-panel 应注册 dao.proxyPro");
});

test("Windows 管理 = 归一面板子板块（单页统管, 官方 mstsc 收编经 __DAO_WIN_HOME__ 上交）", () => {
  const ext = fs.readFileSync(path.join(ROOT, "extension.js"), "utf8");
  assert.ok(ext.includes("globalThis.__DAO_WIN_HOME__"), "宿主应上交 Windows 总控原语");
  assert.ok(!ext.includes('createWebviewPanel("daoWinHome"'), "不应另起独立主页 webview（单页统管）");
  assert.ok(ext.includes('"dao.unified.open"'), "daoWin.home 应聚焦归一面板");
  const uni = fs.readFileSync(path.join(ROOT, "dao-ai-base", "dao-cascade", "unified-panel.js"), "utf8");
  for (const t of ["win-rdp-save", "win-rdp-del", "win-rdp-launch", "win-sub-toggle", "win-reveal-dir", "__DAO_WIN_HOME__", "renderWinRdp", "renderWinHomeCard"])
    assert.ok(uni.includes(t), "归一面板缺 " + t);
  assert.ok(!uni.includes("主页 · Windows 总控"), "主页应复位为归一总览，Windows 只留环境卡");
});

test("机控桥自启与健康指纹（embedded Python 兼容 + apps 数组校验）", () => {
  const ext = fs.readFileSync(path.join(ROOT, "extension.js"), "utf8");
  assert.ok(ext.includes("sys.path.insert(0,"), "自启桥应经 -c 注入 sys.path（embedded 发行版兼容）");
  assert.ok(!ext.includes('"-m", "bridge.server"'), "不应再用 -m bridge.server（embedded ._pth 下必失败）");
  assert.ok(ext.includes("Array.isArray(r.body.apps)"), "tryHealth 应校验 apps 指纹，防他服务 ok:true 误连");
});
