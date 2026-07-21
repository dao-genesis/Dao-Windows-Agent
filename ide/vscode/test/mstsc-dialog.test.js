"use strict";
// 官方「远程桌面连接」(mstsc)对话框收编护栏：
// 1) 归一面板 RDP 表单必须是官方五页页签（常规/显示/本地资源/体验/高级）与官方控件措辞；
// 2) rdpFileContent 生成的 .rdp 必须覆盖官方五页对应的标准键，缺省值与 mstsc 出厂默认一致。
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const Module = require("module");

const ROOT = path.join(__dirname, "..");

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
const { rdpFileContent } = require("../extension");
Module._load = origLoad;

function parseRdp(s) {
  const m = {};
  for (const line of s.split("\r\n")) {
    const i1 = line.indexOf(":"), i2 = line.indexOf(":", i1 + 1);
    if (i1 < 0 || i2 < 0) continue;
    m[line.slice(0, i1)] = line.slice(i2 + 1);
  }
  return m;
}

test("归一面板 RDP 表单 = 官方对话框五页页签与官方控件", () => {
  const uni = fs.readFileSync(path.join(ROOT, "dao-ai-base", "dao-cascade", "unified-panel.js"), "utf8");
  for (const t of ["data-wtab", "wtab_general", "wtab_display", "wtab_local", "wtab_exp", "wtab_adv"])
    assert.ok(uni.includes(t), "缺五页页签要素 " + t);
  for (const t of [
    "计算机(C)", "允许我保存凭据(R)",
    "选择远程桌面的大小", "将我的所有监视器用于远程会话(U)", "最高质量(32 位)", "全屏显示时显示连接栏(D)",
    "远程音频播放", "远程音频录制", "应用 Windows 组合键(K)", "打印机(T)", "剪贴板(L)", "智能卡", "其他支持的即插即用设备",
    "自动检测连接质量(A)", "持久性位图缓存(P)", "如果连接中断则重新连接(R)",
    "如果服务器身份验证失败(F)", "连接而不发出警告", "自动检测 RD 网关服务器设置(A)",
  ]) assert.ok(uni.includes(t), "缺官方控件措辞 " + t);
});

test("默认 .rdp 与官方 mstsc 出厂默认一致", () => {
  const m = parseRdp(rdpFileContent({ name: "t", host: "pc1" }));
  assert.equal(m["full address"], "pc1");
  assert.equal(m["screen mode id"], "2");
  assert.equal(m["session bpp"], "32");
  assert.equal(m["displayconnectionbar"], "1");
  assert.equal(m["audiomode"], "0");
  assert.equal(m["audiocapturemode"], "0");
  assert.equal(m["keyboardhook"], "2");
  assert.equal(m["redirectclipboard"], "1");
  assert.equal(m["redirectprinters"], "0");
  assert.equal(m["redirectsmartcards"], "1");
  assert.equal(m["redirectcomports"], "0");
  assert.equal(m["drivestoredirect"], "");
  assert.equal(m["connection type"], "7");
  assert.equal(m["networkautodetect"], "1");
  assert.equal(m["bandwidthautodetect"], "1");
  assert.equal(m["disable wallpaper"], "0");
  assert.equal(m["allow font smoothing"], "0");
  assert.equal(m["disable full window drag"], "1");
  assert.equal(m["disable menu anims"], "1");
  assert.equal(m["disable themes"], "0");
  assert.equal(m["bitmapcachepersistenable"], "1");
  assert.equal(m["autoreconnection enabled"], "1");
  assert.equal(m["authentication level"], "2");
  assert.equal(m["gatewayusagemethod"], "4");
  assert.equal(m["gatewayprofileusagemethod"], "0");
  assert.equal(m["promptcredentialonce"], "1");
});

test("五页配置逐控件映射标准 .rdp 键", () => {
  const m = parseRdp(rdpFileContent({
    name: "t", host: "pc1", port: 3390, username: "u1", savecred: true,
    fullscreen: false, width: 1280, height: 720, multimon: true, bpp: 24, connbar: false,
    audiomode: 1, audiocapture: 1, keyboardhook: 0, clipboard: false, printers: true,
    smartcards: false, ports: true, drives: true, pnp: true,
    conntype: 6, wallpaper: false, fontsmoothing: true, composition: true,
    fullwindowdrag: true, menuanims: true, themes: false, bitmapcache: false, autoreconnect: false,
    authlevel: 0, gwmethod: "manual", gateway: "gw.fabrikam.com", gwbypass: false, gwcreds: false,
  }));
  assert.equal(m["full address"], "pc1:3390");
  assert.equal(m["username"], "u1");
  assert.equal(m["prompt for credentials"], "0");
  assert.equal(m["screen mode id"], "1");
  assert.equal(m["desktopwidth"], "1280");
  assert.equal(m["desktopheight"], "720");
  assert.equal(m["use multimon"], "1");
  assert.equal(m["session bpp"], "24");
  assert.equal(m["displayconnectionbar"], "0");
  assert.equal(m["audiomode"], "1");
  assert.equal(m["audiocapturemode"], "1");
  assert.equal(m["keyboardhook"], "0");
  assert.equal(m["redirectclipboard"], "0");
  assert.equal(m["redirectprinters"], "1");
  assert.equal(m["redirectsmartcards"], "0");
  assert.equal(m["redirectcomports"], "1");
  assert.equal(m["drivestoredirect"], "*");
  assert.equal(m["devicestoredirect"], "*");
  assert.equal(m["connection type"], "6");
  assert.equal(m["networkautodetect"], "0");
  assert.equal(m["bandwidthautodetect"], "0");
  assert.equal(m["disable wallpaper"], "1");
  assert.equal(m["allow font smoothing"], "1");
  assert.equal(m["allow desktop composition"], "1");
  assert.equal(m["disable full window drag"], "0");
  assert.equal(m["disable menu anims"], "0");
  assert.equal(m["disable themes"], "1");
  assert.equal(m["bitmapcachepersistenable"], "0");
  assert.equal(m["autoreconnection enabled"], "0");
  assert.equal(m["authentication level"], "0");
  assert.equal(m["gatewayhostname"], "gw.fabrikam.com");
  assert.equal(m["gatewayusagemethod"], "1");
  assert.equal(m["gatewayprofileusagemethod"], "1");
  assert.equal(m["promptcredentialonce"], "0");
});

test("RD 网关三种连接方法与官方语义一致（自动/手动含绕过/不使用）", () => {
  assert.equal(parseRdp(rdpFileContent({ name: "t", gwmethod: "auto" }))["gatewayusagemethod"], "4");
  assert.equal(parseRdp(rdpFileContent({ name: "t", gwmethod: "none" }))["gatewayusagemethod"], "0");
  assert.equal(parseRdp(rdpFileContent({ name: "t", gwmethod: "manual", gateway: "g", gwbypass: true }))["gatewayusagemethod"], "2");
  // 旧存量 profile（只有 gateway 字段）→ 手动方法, 与旧行为兼容
  assert.equal(parseRdp(rdpFileContent({ name: "t", gateway: "g" }))["gatewayhostname"], "g");
});
