// 归一宿主接线护栏（归一本体化后）：本插件本体前端 = 内置归一面板(dao.unified·同一底层)，
// 🪟 Windows 为其中板块；与 Devin Desktop 的 dao-one 仅靠扩展名/宿主 IDE 隔离，不再另起独立总控架构。
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

test("package.json 贡献内置归一面板视图（同一底层 · 🪟 Windows 为其中板块）", () => {
  const views = (pkg.contributes.views || {})["dao-unified"] || [];
  assert.ok(views.some((x) => x.id === "dao.unified"), "应贡献 dao.unified 侧栏视图（归一本体前端）");
  assert.ok(
    (pkg.contributes.commands || []).some((c) => c.command === "dao.unified.open"),
    "应贡献 dao.unified.open（归一面板入口）"
  );
});

test("激活链启用内置归一面板（unified:true），主页默认归一，旧独立页仅作兜底", () => {
  const ext = fs.readFileSync(path.join(ROOT, "extension.js"), "utf8");
  assert.ok(ext.includes("unified: true"), "activateDaoAiBase 应传 unified:true（归一本体化）");
  assert.ok(ext.includes('executeCommand("dao.unified.focus")'), "默认主页应聚焦内置归一面板");
  assert.ok(ext.includes('createWebviewPanel("daoWinHome"'), "旧独立页应保留为兜底 webview");
  assert.ok(ext.includes(String.raw`mode === "dao-one"`), "dao-one 委派只允许显式 homeMode=dao-one");
});

test("主页默认归一 + 自有桥口 9930（与 Devin Desktop 的 dao-one 靠 IDE/端口隔离）", () => {
  const props = pkg.contributes.configuration.properties;
  assert.strictEqual(props["daoWin.homeMode"].default, "unified", "默认主页应为内置归一面板");
  assert.ok(props["daoWin.homeMode"].enum.includes("standalone"), "应保留 standalone 兜底模式");
  assert.ok(props["daoWin.bridgeUrl"].default.includes(":9930"), "桥口应与 dao-one/dao-vsix 的 9920/9921 分离");
});

test("Windows 总控原语默认上交供内置归一面板渲染（同一底层·融为一体）", () => {
  const ext = fs.readFileSync(path.join(ROOT, "extension.js"), "utf8");
  assert.ok(ext.includes("winHomeApi = {"), "installWinHomeHook 应把原语存入模块内 winHomeApi");
  assert.ok(ext.includes("function publishWinHomeHook()"), "应存在唯一上交函数 publishWinHomeHook");
  assert.ok(
    /publishWinHomeHook\(\);\s*\}\s*\n\s*\/\/ 上交/.test(ext) || /\n  publishWinHomeHook\(\);\n\}/.test(ext),
    "installWinHomeHook 尾部应默认调用 publishWinHomeHook（内置归一面板即消费方）"
  );
  assert.ok(ext.includes("winHomeApi || globalThis.__DAO_WIN_HOME__"), "自读原语应优先模块内 winHomeApi");
});

test("🪟 板块 RDP 配置表单带顶部返回键（配置流不断路）", () => {
  const up = fs.readFileSync(path.join(ROOT, "dao-ai-base", "dao-cascade", "unified-panel.js"), "utf8");
  assert.ok(up.includes('id="winRdpBack"'), "归一面板 RDP 表单应有顶部返回键");
  assert.ok(/winRdpBack'\); if\(wrb\)wrb\.onclick/.test(up), "返回键应绑回连接列表");
  const wh = fs.readFileSync(path.join(ROOT, "win-home.js"), "utf8");
  assert.ok(wh.includes("\\u2190 \\u8fd4\\u56de\\u8fde\\u63a5\\u5217\\u8868"), "兜底页 mstsc 表单也应有顶部返回键");
});

test("dao-ai-base 保留 unified 开关（默认开启，宿主可显式关闭）", () => {
  const idx = fs.readFileSync(path.join(ROOT, "dao-ai-base", "index.js"), "utf8");
  assert.ok(idx.includes("o.unified !== false"), "index.js 应支持 unified 开关");
});

test("机控桥自启与健康指纹（embedded Python 兼容 + apps 数组校验）", () => {
  const ext = fs.readFileSync(path.join(ROOT, "extension.js"), "utf8");
  assert.ok(ext.includes("sys.path.insert(0,"), "自启桥应经 -c 注入 sys.path（embedded 发行版兼容）");
  assert.ok(!ext.includes('"-m", "bridge.server"'), "不应再用 -m bridge.server（embedded ._pth 下必失败）");
  assert.ok(ext.includes("Array.isArray(r.body.apps)"), "tryHealth 应校验 apps 指纹，防他服务 ok:true 误连");
});
