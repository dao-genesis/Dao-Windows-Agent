// 归一宿主接线护栏（正本清源后）：归一宿主唯一 = 原 dao-one/9920 全能板，
// 🪟 Windows 经 dao-one-windows 衍生注入为其同级 tab；本仓不得再自建归一/Proxy Pro 侧栏顶替本源。
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));

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

test("激活链停用自建归一面板（unified:false），归一主页指向 dao-one 全能板", () => {
  const ext = fs.readFileSync(path.join(ROOT, "extension.js"), "utf8");
  assert.ok(ext.includes("unified: false"), "activateDaoAiBase 应传 unified:false");
  assert.ok(ext.includes('executeCommand("dao.openCloudPanel")'), "daoWin.home 应打开原 dao-one 全能板");
  assert.ok(!ext.includes('executeCommand("dao.unified.open")'), "不应再回退自建 dao.unified 面板");
  assert.ok(!ext.includes('createWebviewPanel("daoWinHome"'), "不应另起独立主页 webview");
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
