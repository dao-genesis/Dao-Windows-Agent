#!/usr/bin/env node
// dao-proxy-pro/sync.js — 从真源 windsurf-assistant 重新 vendor SP 引擎薄片。
// 用法: node sync.js /path/to/windsurf-assistant
//   · 复制 sp_invert.js(唯一改动: _BUNDLED_DIR 指向本目录 bundled-origin/)
//   · 复制经藏文本 bundled-origin/{_silk_de,_silk_dao,_yinfu}.txt
const fs = require("fs");
const path = require("path");

const src = process.argv[2];
if (!src) { console.error("用法: node sync.js /path/to/windsurf-assistant"); process.exit(1); }
// 真源布局候选: 旧布局 plugins/… → 新布局 packages/…(上游自同步的发布快照)。
// 上游 plugins/dao-proxy-pro 已重构(sp_invert 不再在该路径), packages/ 保持旧形状。
const candidates = [
  path.join(src, "plugins", "dao-proxy-pro", "vendor"),
  path.join(src, "packages", "dao-proxy-pro", "vendor"),
];
const pp = candidates.find((d) => fs.existsSync(path.join(d, "外接api", "core", "sp_invert.js")));
if (!pp) { console.error("真源不存在(两套布局均未命中): " + candidates.join(" | ")); process.exit(1); }
const engine = path.join(pp, "外接api", "core", "sp_invert.js");

let code = fs.readFileSync(engine, "utf8");
const before = 'path.resolve(__dirname, "..", "..", "bundled-origin")';
const after = 'path.join(__dirname, "bundled-origin")';
if (code.indexOf(before) < 0 && code.indexOf(after) < 0) {
  console.error("_BUNDLED_DIR 形状变化, 请人工核对真源"); process.exit(1);
}
code = code.split(before).join(after);

// 本仓本地补丁: 模式契约(~/.dao/mode.json · ModeManager 联动)。上游若尚未回灌该补丁,
// 直接覆盖会丢失三插件融合枢纽 —— 拒绝静默覆盖, 提示人工重打(见 VENDOR.md)。
if (code.indexOf("mode.json") < 0) {
  const cur = fs.readFileSync(path.join(__dirname, "sp_invert.js"), "utf8");
  if (cur.indexOf("mode.json") >= 0) {
    console.error("上游尚无模式契约补丁(mode.json), 直接同步会丢失本仓补丁; 请先回灌上游或同步后人工重打(见 VENDOR.md)。");
    process.exit(1);
  }
}
fs.writeFileSync(path.join(__dirname, "sp_invert.js"), code);

// 经藏文本: 旧布局在 pp/bundled-origin; 新布局迁至 packages/dao-proxy-min/vendor/bundled-origin(同源同文)。
const canonSrcCandidates = [
  path.join(pp, "bundled-origin"),
  path.join(src, "packages", "dao-proxy-min", "vendor", "bundled-origin"),
];
const canonSrc = canonSrcCandidates.find((d) => fs.existsSync(path.join(d, "_silk_de.txt")));
if (!canonSrc) { console.error("经藏文本不存在: " + canonSrcCandidates.join(" | ")); process.exit(1); }
const canonDst = path.join(__dirname, "bundled-origin");
fs.mkdirSync(canonDst, { recursive: true });
for (const f of ["_silk_de.txt", "_silk_dao.txt", "_yinfu.txt"]) {
  fs.copyFileSync(path.join(canonSrc, f), path.join(canonDst, f));
}

const vendorMd = path.join(__dirname, "VENDOR.md");
const md = fs.readFileSync(vendorMd, "utf8").replace(/同步时间: .*/g, "同步时间: " + new Date().toISOString());
fs.writeFileSync(vendorMd, md);
console.log("✓ sp_invert.js + 经藏 已同步自 " + pp);
