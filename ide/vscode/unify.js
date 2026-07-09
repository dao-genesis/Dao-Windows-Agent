#!/usr/bin/env node
// 二合一构建装配(参照 devin-remote/dao-one): 把各领域插件折入 vendor/<名>/,
// 并把它们的 contributes 合入本插件 package.json —— 一个 VSIX 统领 Windows 主体 +
// AI 交互基底 + 各领域子模块, 规避 VS Code 插件相互隔离。
//
// 用法: node unify.js <领域插件目录>... [--clean]
// 例:   node unify.js \
//         ~/repos/Dao-3D-Modeling-Agent/90-归一_IDE/vscode-dao-freecad \
//         ~/repos/Dao-PCB-Design-Agent/vscode-dao-kicad \
//         ~/repos/Dao-PCB-Design-Agent/vscode-dao-lceda \
//         ~/repos/ha-copilot/ide-extension
// vendor/ 不入库(构建产物); 缺哪个源目录就跳过哪个(樸散則為器, 有则收编, 无则自然)。
"use strict";
const fs = require("fs");
const path = require("path");

const here = __dirname;
const args = process.argv.slice(2);
const clean = args.includes("--clean");
const sources = args.filter((a) => a !== "--clean");

const vendorRoot = path.join(here, "vendor");
if (clean) { fs.rmSync(vendorRoot, { recursive: true, force: true }); console.log("✓ vendor/ 已清空"); }
if (!sources.length) { console.log("(无源目录参数, 仅清理)"); process.exit(0); }

function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".git" || e.name.endsWith(".vsix")) continue;
    const s = path.join(src, e.name), d = path.join(dst, e.name);
    e.isDirectory() ? copyDir(s, d) : fs.copyFileSync(s, d);
  }
}

// contributes 深合并: 按 command/view/container id 去重, 后到覆盖同 id 旧项。
function mergeContributes(host, sub) {
  if (!sub) return;
  host.viewsContainers = host.viewsContainers || {};
  const hAct = (host.viewsContainers.activitybar = host.viewsContainers.activitybar || []);
  for (const v of (sub.viewsContainers && sub.viewsContainers.activitybar) || []) {
    const i = hAct.findIndex((x) => x.id === v.id);
    i >= 0 ? (hAct[i] = v) : hAct.push(v);
  }
  host.views = host.views || {};
  for (const [k, arr] of Object.entries(sub.views || {})) {
    const hv = (host.views[k] = host.views[k] || []);
    for (const v of arr) {
      const i = hv.findIndex((x) => x.id === v.id);
      i >= 0 ? (hv[i] = v) : hv.push(v);
    }
  }
  host.commands = host.commands || [];
  for (const c of sub.commands || []) {
    const i = host.commands.findIndex((x) => x.command === c.command);
    i >= 0 ? (host.commands[i] = c) : host.commands.push(c);
  }
  host.menus = host.menus || {};
  for (const [k, arr] of Object.entries(sub.menus || {})) {
    const hm = (host.menus[k] = host.menus[k] || []);
    for (const m of arr) {
      const i = hm.findIndex((x) => x.command === m.command && x.when === m.when);
      i >= 0 ? (hm[i] = m) : hm.push(m);
    }
  }
  // configuration: 可为对象或数组, 归一为数组并按 title 去重。
  if (sub.configuration) {
    const toArr = (c) => (Array.isArray(c) ? c : [c]);
    const hc = (host.configuration = host.configuration ? toArr(host.configuration) : []);
    for (const c of toArr(sub.configuration)) {
      const i = hc.findIndex((x) => x.title === c.title);
      i >= 0 ? (hc[i] = c) : hc.push(c);
    }
  }
}

const pkgPath = path.join(here, "package.json");
const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
pkg.contributes = pkg.contributes || {};

let folded = 0;
for (const src of sources) {
  const abs = path.resolve(src.replace(/^~(?=$|\/)/, process.env.HOME || "~"));
  if (!fs.existsSync(path.join(abs, "extension.js")) || !fs.existsSync(path.join(abs, "package.json"))) {
    console.log("→ 跳过(缺 extension.js/package.json): " + abs);
    continue;
  }
  const subPkg = JSON.parse(fs.readFileSync(path.join(abs, "package.json"), "utf8"));
  const name = String(subPkg.name || path.basename(abs));
  const dst = path.join(vendorRoot, name);
  fs.rmSync(dst, { recursive: true, force: true });
  copyDir(abs, dst);
  mergeContributes(pkg.contributes, subPkg.contributes);
  folded++;
  console.log("✓ 折入 [" + name + "] " + abs + " → vendor/" + name);
}

fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + "\n");
console.log("✓ contributes 已合入 package.json · 共折入 " + folded + " 个子模块");
