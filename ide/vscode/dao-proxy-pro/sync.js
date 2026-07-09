#!/usr/bin/env node
// dao-proxy-pro/sync.js — 从真源 windsurf-assistant 重新 vendor SP 引擎薄片。
// 用法: node sync.js /path/to/windsurf-assistant
//   · 复制 sp_invert.js(唯一改动: _BUNDLED_DIR 指向本目录 bundled-origin/)
//   · 复制经藏文本 bundled-origin/{_silk_de,_silk_dao,_yinfu}.txt
const fs = require("fs");
const path = require("path");

const src = process.argv[2];
if (!src) { console.error("用法: node sync.js /path/to/windsurf-assistant"); process.exit(1); }
const pp = path.join(src, "plugins", "dao-proxy-pro", "vendor");
const engine = path.join(pp, "外接api", "core", "sp_invert.js");
if (!fs.existsSync(engine)) { console.error("真源不存在: " + engine); process.exit(1); }

let code = fs.readFileSync(engine, "utf8");
const before = 'path.resolve(__dirname, "..", "..", "bundled-origin")';
const after = 'path.join(__dirname, "bundled-origin")';
if (code.indexOf(before) < 0 && code.indexOf(after) < 0) {
  console.error("_BUNDLED_DIR 形状变化, 请人工核对真源"); process.exit(1);
}
code = code.split(before).join(after);
fs.writeFileSync(path.join(__dirname, "sp_invert.js"), code);

const canonDst = path.join(__dirname, "bundled-origin");
fs.mkdirSync(canonDst, { recursive: true });
for (const f of ["_silk_de.txt", "_silk_dao.txt", "_yinfu.txt"]) {
  fs.copyFileSync(path.join(pp, "bundled-origin", f), path.join(canonDst, f));
}

const vendorMd = path.join(__dirname, "VENDOR.md");
const md = fs.readFileSync(vendorMd, "utf8").replace(/同步时间: .*/g, "同步时间: " + new Date().toISOString());
fs.writeFileSync(vendorMd, md);
console.log("✓ sp_invert.js + 经藏 已同步自 " + pp);
