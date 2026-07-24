#!/usr/bin/env node
// dao-one-windows · 常驻再注入器(反者道之动) — dao-vsix 自更新会以官方 dao-one Release
// 覆盖 vendor-vsix/out/extension.js 抹掉 🪟 板块; 本器由计划任务在登录时+周期性运行,
// 一旦发现加载版「缺补丁」或「补丁过时」即就地重折入(幂等), 使成果长驻真机、
// 重启/自更新皆不丢, 且负载升级后旧注入不会把新成果挡在门外。
//
// 三态判定(以首行标记「dao-one-windows applied sig=<PAYLOAD_SIG>」为准):
//   ① 未注入(无 MARK)              → 以当前文件为真源折入, 备份 .prewin;
//   ② 已注入且 sig 一致            → OK, 不动;
//   ③ 已注入但 sig 不一致(过时)     → 从 .prewin 真源(未注入的官方版)以当前负载重折入;
//      缺 .prewin 时守柔跳过(不拿注入过的文件当真源, 免叠加/错插)。
"use strict";
const fs = require("fs");
const path = require("path");
const os = require("os");
const http = require("http");
const { applyPatches, MARK, APPLIED_TAG } = require("./inject");

// 就地重载 dao-vsix(不重装·仅让宿主重读被折入的 vendor 模块)。token 从本机同目录 .bridge-token
// 读取(用户本机自有令牌·绝不入库/入 PR)。缺 token 则跳过重载(板块于用户下次窗口重载自然生效)。
function reloadBridge() {
  let token = "";
  try { token = fs.readFileSync(path.join(__dirname, ".bridge-token"), "utf8").trim(); } catch (e) { /* 守柔 */ }
  if (!token) { console.log("RELOAD_SKIP no-token"); return; }
  const body = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call",
    params: { name: "plugin_reload", arguments: { confirm: true } } });
  const req = http.request({ host: "127.0.0.1", port: 9920, path: "/mcp", method: "POST",
    headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body),
      "Authorization": "Bearer " + token } },
    (res) => { let d = ""; res.on("data", (c) => d += c); res.on("end", () => console.log("RELOAD " + res.statusCode)); });
  req.on("error", (e) => console.log("RELOAD_ERR " + (e && e.message || e)));
  req.write(body); req.end();
}

function verKey(name) {
  const m = /dao\.dao-one-(\d+)\.(\d+)\.(\d+)/.exec(name);
  return m ? [+m[1], +m[2], +m[3]] : [0, 0, 0];
}
function cmp(a, b) { for (let i = 0; i < 3; i++) { if (a[i] !== b[i]) return a[i] - b[i]; } return 0; }

function highestDaoOne() {
  const base = path.join(os.homedir(), ".vscode", "extensions");
  let best = null;
  for (const n of fs.readdirSync(base)) {
    if (!/^dao\.dao-one-\d+\.\d+\.\d+$/.test(n)) continue;
    const f = path.join(base, n, "vendor-vsix", "out", "extension.js");
    if (!fs.existsSync(f)) continue;
    if (!best || cmp(verKey(n), verKey(best.name)) > 0) best = { name: n, file: f };
  }
  return best;
}

// 折入并落盘。真源 pristineSrc(未注入的官方版)与目标文件 file 可不同(过时重折时
// 真源取自 .prewin)。首次折入时把真源备份到 .prewin, 供日后过时重折。
function injectTo(file, pristineSrc, reason) {
  let patched;
  try { patched = applyPatches(pristineSrc); }
  catch (e) { console.log("ANCHOR_FAIL " + reason + " :: " + (e && e.message || e)); return 2; }
  try { if (!fs.existsSync(file + ".prewin")) fs.writeFileSync(file + ".prewin", pristineSrc, "utf8"); } catch (e) { /* 守柔 */ }
  fs.writeFileSync(file, patched, "utf8");
  console.log(reason + " " + file);
  reloadBridge();
  return 10; // 10 = 本次发生了再注入(已请求重载)
}

function main() {
  const t = highestDaoOne();
  if (!t) { console.log("NO_DAO_ONE"); return 0; }
  const src = fs.readFileSync(t.file, "utf8");

  // ② 已注入且最新
  if (src.includes(APPLIED_TAG)) { console.log("OK_CURRENT " + t.name); return 0; }

  // ③ 已注入但过时(有 MARK 无当前 sig): 必须从 .prewin 真源重折, 不拿注入过的文件当真源
  if (src.includes(MARK + " applied")) {
    const pw = t.file + ".prewin";
    if (!fs.existsSync(pw)) { console.log("STALE_NO_PREWIN " + t.name); return 3; }
    const pristine = fs.readFileSync(pw, "utf8");
    if (pristine.includes(MARK + " applied")) { console.log("PREWIN_TAINTED " + t.name); return 3; }
    return injectTo(t.file, pristine, "REINJECTED_STALE");
  }

  // ① 未注入: 以当前文件为真源折入
  return injectTo(t.file, src, "REINJECTED");
}

const rc = main();
// 给异步重载请求留出发出的时间窗
setTimeout(() => process.exit(rc), 1500);
