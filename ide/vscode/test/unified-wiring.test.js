// 归一宿主接线护栏（正本清源后）：归一宿主唯一 = 原 dao-one/9920 全能板，
// 🪟 Windows 经 dao-one-windows 衍生注入为其同级 tab；本仓不得再自建归一/Proxy Pro 侧栏顶替本源。
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));

test("Windows 桌面插件身份与 dao-one 隔离", () => {
  assert.strictEqual(pkg.publisher, "daowin", "publisher 不应继续占用 dao 命名空间");
  assert.strictEqual(pkg.name, "dao-windows-desktop", "扩展 ID 应独立于旧 dao.dao-windows-agent");
});

test("package.json 不再贡献自建 dao.unified / dao.proxyPro 视图（归一宿主唯一 = dao-one）", () => {
  const views = (pkg.contributes.views || {})["daoWin-cascade"] || [];
  for (const id of ["dao.unified", "dao.proxyPro"]) {
    assert.ok(!views.some((x) => x.id === id), id + " 不应再作为本仓侧栏视图（错位宿主）");
  }
  assert.ok(
    !(pkg.contributes.commands || []).some((c) => c.command === "dao.unified.open"),
    "不应再贡献 dao.unified.open（自建面板入口）"
  );
});

test("激活链停用自建归一面板（unified:false），主页默认独立宿主（真隔离）", () => {
  const ext = fs.readFileSync(path.join(ROOT, "extension.js"), "utf8");
  assert.ok(ext.includes("unified: false"), "activateDaoAiBase 应传 unified:false");
  assert.ok(ext.includes('createWebviewPanel("daoWinHome"'), "主页应为本插件独立总控 webview");
  assert.ok(ext.includes('homeMode === "dao-one"'), "dao-one 委派只允许显式 homeMode=dao-one");
  assert.ok(!ext.includes('executeCommand("dao.unified.open")'), "不应再回退自建 dao.unified 面板");
});

test("主页/桥口配置真隔离（standalone 默认 + 自有桥口 9930）", () => {
  const props = pkg.contributes.configuration.properties;
  assert.strictEqual(props["daoWin.homeMode"].default, "standalone", "默认主页应为独立宿主");
  assert.ok(props["daoWin.bridgeUrl"].default.includes(":9930"), "桥口应与 dao-one/dao-vsix 的 9920/9921 分离");
});

test("dao-ai-base 保留 unified 开关且默认可被宿主关闭", () => {
  const idx = fs.readFileSync(path.join(ROOT, "dao-ai-base", "index.js"), "utf8");
  assert.ok(idx.includes("o.unified !== false"), "index.js 应支持 unified:false 停用自建面板");
});

test("机控桥自启与健康指纹（embedded Python 兼容 + apps 数组校验）", () => {
  const ext = fs.readFileSync(path.join(ROOT, "extension.js"), "utf8");
  assert.ok(ext.includes("sys.path.insert(0,"), "自启桥应经 -c 注入 sys.path（embedded 发行版兼容）");
  assert.ok(!ext.includes('"-m", "bridge.server"'), "不应再用 -m bridge.server（embedded ._pth 下必失败）");
  assert.ok(ext.includes("Array.isArray(r.body.apps)"), "tryHealth 应校验 apps 指纹，防他服务 ok:true 误连");
});
