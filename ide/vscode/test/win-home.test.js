"use strict";
// 独立总控主页 + 官方设置直通护栏：
// 1) daoWinHome webview 模板脚本语法完好、官方 mstsc 五页控件（官方措辞）齐备；
// 2) 桌面面板官方设置抽屉的查询键 = 隧道 server.js experienceOptsFromQuery 认得的键；
// 3) .rdp 档案键 → token 查询串（rdpProfileTokenQuery）逐键正确。
const { test } = require("node:test");
const assert = require("node:assert");
const path = require("path");
const Module = require("module");

const fakeVscode = {
  Uri: { joinPath: () => ({ toString: () => "vscode-resource://media" }) },
  workspace: { getConfiguration: () => ({ get: () => undefined }) },
};
const origLoad = Module._load;
// guacamole-lite 仅在真隧道运行时需要；headless 单测只取 server.js 的纯函数，用桩顶替。
Module._load = function (request) {
  if (request === "vscode") return fakeVscode;
  if (request === "guacamole-lite") return class GuacamoleLiteStub {};
  if (request === "guacamole-lite/lib/Crypt") return class CryptStub { encrypt() { return "stub-token"; } };
  if (request === "ws") return { WebSocket: class {}, WebSocketServer: class {} };
  return origLoad.apply(this, arguments);
};
const { rdpProfileTokenQuery, desktopHtml } = require("../extension");
const { experienceOptsFromQuery } = require(path.join(__dirname, "..", "..", "..", "desktop", "tunnel", "server.js"));
Module._load = origLoad;
const { winHomeHtml } = require("../win-home");

const STATE = {
  sessionId: "ide_testhash",
  platform: "win32",
  rdp: [{ name: "lab", host: "10.0.0.2", port: "3389", username: "dao" }],
  accounts: [{ name: "dao", hostname: "127.0.0.1", port: "13389" }],
};

test("独立总控主页内联脚本语法完好（可被解析）", () => {
  const html = winHomeHtml(STATE);
  const m = html.match(/<script>([\s\S]*)<\/script>/);
  assert.ok(m, "应含内联脚本");
  assert.doesNotThrow(() => new Function(m[1]), "内联脚本必须无语法错误");
});

test("官方 mstsc 五页控件（官方措辞）在独立主页内", () => {
  const html = winHomeHtml(STATE);
  for (const t of ["wtab_general", "wtab_display", "wtab_local", "wtab_exp", "wtab_adv"]) {
    assert.ok(html.includes(t), "缺五页页签要素 " + t);
  }
  for (const s of [
    "计算机(C)", "允许我保存凭据(R)", "选择远程桌面的大小", "将我的所有监视器用于远程会话(U)",
    "最高质量(32 位)", "全屏显示时显示连接栏(D)", "远程音频播放", "远程音频录制",
    "应用 Windows 组合键(K)", "打印机(T)", "剪贴板(L)", "智能卡", "其他支持的即插即用设备",
    "自动检测连接质量(A)", "持久性位图缓存(P)", "如果连接中断则重新连接(R)",
    "如果服务器身份验证失败(F)", "连接而不发出警告", "自动检测 RD 网关服务器设置(A)",
  ]) {
    assert.ok(html.includes(s), "缺官方控件措辞: " + s);
  }
  assert.ok(html.includes("账号池"), "缺账号池板块");
  assert.ok(!html.includes("dao.openCloudPanel"), "独立主页不得依赖归一宿主命令");
});

test("桌面面板官方设置抽屉键与隧道 experienceOptsFromQuery 对齐", () => {
  const html = desktopHtml(
    { cspSource: "vscode-resource:", asWebviewUri: (u) => u },
    { extensionUri: {} }, "ide_testhash", "dao",
    "http://127.0.0.1:4824", 4823, [{ name: "dao" }], "t", "&colordepth=16"
  );
  for (const id of [
    "st_colordepth", "st_gfx", "st_lossless", "st_clipboard", "st_audio", "st_printing",
    "st_drive", "st_wallpaper", "st_theming", "st_fontsmoothing", "st_windowdrag",
    "st_composition", "st_animations", "st_bitmapcache", "st_layout", "st_timezone",
    "st_readonly", "st_console",
  ]) {
    assert.ok(html.includes('id="' + id + '"'), "缺设置控件 " + id);
  }
  assert.ok(html.includes("settingsQuery()"), "连接取 token 时必须携带设置查询串");
  assert.ok(html.includes("EXTRA_Q"), "档案预置参数必须注入桌面面板");
  assert.ok(html.includes("sendCtrlAltDel"), "缺 Ctrl+Alt+Del 会话操作");
  const served = ["gfx", "lossless", "colordepth", "wallpaper", "theming", "fontsmoothing",
    "windowdrag", "composition", "animations", "bitmapcache", "audio", "printing", "layout", "timezone", "console"];
  for (const k of served) {
    assert.ok(html.includes("'&" + k + "='") || html.includes("'" + k + "'") || html.includes(k + "="), "设置键未见于面板: " + k);
  }
  const sp = new URLSearchParams(
    "gfx=1&lossless=0&colordepth=16&wallpaper=1&theming=0&fontsmoothing=1&windowdrag=1&composition=1&animations=1&bitmapcache=0&audio=both&printing=1&layout=en-us-qwerty&timezone=Asia/Shanghai&console=1"
  );
  const opts = experienceOptsFromQuery(sp);
  for (const [k, v] of Object.entries({
    gfx: "1", lossless: "0", colorDepth: "16", wallpaper: "1", theming: "0",
    fontSmoothing: "1", fullWindowDrag: "1", desktopComposition: "1", menuAnimations: "1",
    bitmapCache: "0", audio: "both", printing: "1", serverLayout: "en-us-qwerty",
    timezone: "Asia/Shanghai", console: "1",
  })) {
    assert.strictEqual(opts[k], v, "隧道端应认得设置键 " + k);
  }
});

test("rdpProfileTokenQuery：.rdp 档案键逐键直通 token 查询串", () => {
  assert.strictEqual(rdpProfileTokenQuery(null), "");
  const q = rdpProfileTokenQuery({
    bpp: 16, wallpaper: false, themes: true, fontsmoothing: true, fullwindowdrag: true,
    composition: true, menuanims: true, bitmapcache: false, audiomode: 2, printers: true,
    clipboard: false, drives: true, readonly: true,
  });
  for (const part of [
    "&clipboard=off", "&drive=", "&readonly=1", "&colordepth=16", "&wallpaper=0",
    "&theming=1", "&fontsmoothing=1", "&windowdrag=1", "&composition=1",
    "&animations=1", "&bitmapcache=0", "&audio=off", "&printing=1",
  ]) {
    assert.ok(q.includes(part), "缺档案直通键 " + part + " · 实得 " + q);
  }
  assert.ok(rdpProfileTokenQuery({ audiomode: 0, audiocapture: 1 }).includes("&audio=both"));
  assert.ok(rdpProfileTokenQuery({ audiomode: 1 }).includes("&audio=out"));
});
