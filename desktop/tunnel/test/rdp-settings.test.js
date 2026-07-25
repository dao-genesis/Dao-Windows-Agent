"use strict";
// 官方 RDP 协议全量设置铸造自检（正本清源核心问题②：白屏/卡/未用官方底层的技术真身）：
// 默认启用 GFX(H.264 官方图形管线) + 抗卡体验默认 + 缓存全开；逐项可覆盖；音频/色深/无损/键盘/时区齐备。
// require server.js 不得占端口/连 guacd（纯函数导出）。
const { test } = require("node:test");
const assert = require("node:assert");

// 隔离环境默认（避免宿主 env 影响断言）。
for (const k of Object.keys(process.env)) {
  if (k.startsWith("DAO_RDP_")) delete process.env[k];
}
const srv = require("../server");
const RDP = { hostname: "10.0.0.9", port: "3389", username: "dao", password: "secret" };

test("require server.js 只暴露纯函数，不占端口", () => {
  assert.strictEqual(typeof srv.buildRdpSettings, "function");
  assert.strictEqual(typeof srv.experienceOptsFromQuery, "function");
});

test("默认：GFX(H.264 官方底层)开、抗卡体验默认、缓存全开、音频输出", () => {
  const s = srv.buildRdpSettings(RDP, {});
  // 基础
  assert.strictEqual(s.hostname, "10.0.0.9");
  assert.strictEqual(s.username, "dao");
  assert.strictEqual(s["resize-method"], "display-update");
  // 官方图形底层管线默认开（Win11 24H2 WDDM 保真+流畅之本）
  assert.strictEqual(s["enable-gfx"], "true");
  // 高带宽体验默认关（抗卡）
  assert.ok(!("enable-wallpaper" in s), "壁纸默认关");
  assert.ok(!("enable-full-window-drag" in s), "全窗口拖动默认关");
  assert.ok(!("enable-menu-animations" in s), "菜单动画默认关");
  assert.ok(!("enable-desktop-composition" in s), "桌面合成默认关");
  // 可读性体验默认开
  assert.strictEqual(s["enable-theming"], "true");
  assert.strictEqual(s["enable-font-smoothing"], "true");
  // 缓存默认全开（不设 disable-*）
  assert.ok(!("disable-bitmap-caching" in s));
  assert.ok(!("disable-offscreen-caching" in s));
  assert.ok(!("disable-glyph-caching" in s));
  // 音频默认 out：不禁音频、不开麦克风
  assert.ok(!("disable-audio" in s));
  assert.ok(!("enable-audio-input" in s));
  // 未强制无损、未设色深
  assert.ok(!("force-lossless" in s));
  assert.ok(!("color-depth" in s));
});

test("逐项覆盖：关 GFX 回退老管线、开壁纸/无损、色深、麦克风、打印、键盘/时区", () => {
  const s = srv.buildRdpSettings(RDP, {
    gfx: "0", wallpaper: "1", lossless: true, colorDepth: 16,
    audio: "both", printing: "1", serverLayout: "en-us-qwerty", timezone: "Asia/Shanghai",
    fullWindowDrag: "on", menuAnimations: "yes",
  });
  assert.ok(!("enable-gfx" in s), "gfx=0 应关闭 H.264 管线");
  assert.strictEqual(s["enable-wallpaper"], "true");
  assert.strictEqual(s["force-lossless"], "true");
  assert.strictEqual(s["color-depth"], "16");
  assert.strictEqual(s["enable-audio-input"], "true"); // both = 开麦克风上行
  assert.ok(!("disable-audio" in s), "both 不禁音频输出");
  assert.strictEqual(s["enable-printing"], "true");
  assert.strictEqual(s["server-layout"], "en-us-qwerty");
  assert.strictEqual(s["timezone"], "Asia/Shanghai");
  assert.strictEqual(s["enable-full-window-drag"], "true");
  assert.strictEqual(s["enable-menu-animations"], "true");
});

test("音频 off 禁用；缓存显式关才 disable；色深非法值忽略", () => {
  const off = srv.buildRdpSettings(RDP, { audio: "off", bitmapCache: "0", glyphCache: false, colorDepth: 7 });
  assert.strictEqual(off["disable-audio"], "true");
  assert.ok(!("enable-audio-input" in off));
  assert.strictEqual(off["disable-bitmap-caching"], "true");
  assert.strictEqual(off["disable-glyph-caching"], "true");
  assert.ok(!("disable-offscreen-caching" in off), "未显式关的缓存仍开");
  assert.ok(!("color-depth" in off), "非法色深忽略");
});

test("既有会话策略保留：剪贴板/驱动器/只读/管理会话/域", () => {
  const s = srv.buildRdpSettings(Object.assign({ domain: "CORP" }, RDP), {
    clipboard: "out", drive: "C:\\dao-share", readonly: true, console: "1",
  });
  assert.strictEqual(s["disable-paste"], "true"); // out = 禁本地→远端
  assert.ok(!("disable-copy" in s));
  assert.strictEqual(s["enable-drive"], "true");
  assert.strictEqual(s["drive-path"], "C:\\dao-share");
  assert.strictEqual(s["create-drive-path"], "true");
  assert.strictEqual(s["read-only"], "true");
  assert.strictEqual(s["console"], "true");
  assert.strictEqual(s.domain, "CORP");
});

test("experienceOptsFromQuery：查询参数(含别名)抽取，缺省不设", () => {
  const sp = new URLSearchParams("gfx=0&color-depth=32&fullwindowdrag=1&audio=in&server-layout=de-de-qwertz");
  const o = srv.experienceOptsFromQuery(sp);
  assert.strictEqual(o.gfx, "0");
  assert.strictEqual(o.colorDepth, "32");
  assert.strictEqual(o.fullWindowDrag, "1");
  assert.strictEqual(o.audio, "in");
  assert.strictEqual(o.serverLayout, "de-de-qwertz");
  assert.strictEqual(o.wallpaper, undefined); // 缺省不设
  // 与铸造串联：opts → settings
  const s = srv.buildRdpSettings(RDP, o);
  assert.ok(!("enable-gfx" in s));
  assert.strictEqual(s["color-depth"], "32");
  assert.strictEqual(s["enable-full-window-drag"], "true");
  assert.strictEqual(s["enable-audio-input"], "true");
});

test("triBool 三态语义", () => {
  assert.strictEqual(srv.triBool(undefined), undefined);
  assert.strictEqual(srv.triBool(""), undefined);
  assert.strictEqual(srv.triBool("1"), true);
  assert.strictEqual(srv.triBool("on"), true);
  assert.strictEqual(srv.triBool("false"), false);
  assert.strictEqual(srv.triBool("0"), false);
  assert.strictEqual(srv.triBool("garbage"), undefined);
});
