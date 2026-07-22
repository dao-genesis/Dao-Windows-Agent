#!/usr/bin/env node
// dao-one-windows · 常驻再注入器(反者道之动) — dao-vsix 自更新会以官方 dao-one Release
// 覆盖 vendor-vsix/out/extension.js 抹掉 🪟 板块; 本器由计划任务在登录时+周期性运行,
// 一旦发现加载版缺补丁即就地重折入(幂等), 使成果长驻真机、重启/自更新皆不丢。
"use strict";
const fs = require("fs");
const path = require("path");
const os = require("os");
const http = require("http");
const { applyPatches, MARK } = require("./inject");

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

function main() {
  const t = highestDaoOne();
  if (!t) { console.log("NO_DAO_ONE"); return 0; }
  const src = fs.readFileSync(t.file, "utf8");
  if (src.includes(MARK + " applied")) { console.log("OK_ALREADY " + t.name); return 0; }
  let patched;
  try { patched = applyPatches(src); }
  catch (e) { console.log("ANCHOR_FAIL " + t.name + " :: " + (e && e.message || e)); return 2; }
  try { fs.writeFileSync(t.file + ".prewin", src, "utf8"); } catch (e) { /* 守柔 */ }
  fs.writeFileSync(t.file, patched, "utf8");
  console.log("REINJECTED " + t.name);
  reloadBridge();
  return 10; // 10 = 本次发生了再注入(已请求重载)
}

const rc = main();
// 给异步重载请求留出发出的时间窗
setTimeout(() => process.exit(rc), 1500);
