#!/usr/bin/env node
// dao-one-windows · 衍生注入器 — 在原 dao-one(归一插件)真源上折入 🪟 Windows 板块。
// 本源: 不新建任何前端/宿主, 只对 vendor-vsix/out/extension.js(9920 全能板)做锚点注入:
//   ① _solo 板块白名单 + 侧栏导航 + tv 视图容器 + sw() 分发 → windows 成为与
//      切号/穿透/Proxy/备份 同级的全能板 tab;
//   ② 全能板 <script> 内折入五页 mstsc 表单渲染器;
//   ③ 宿主 handleMiddlePanelMessage 折入 winRdp* 原语(.json+.rdp 落盘 · mstsc.exe 启动);
//   ④ winRdp* 进免登录白名单(RDP 管理与 Devin 账号无关)。
// 用法: node inject.js <dao-one安装目录> <输出目录>
"use strict";
const fs = require("fs");
const path = require("path");
const { FRONTEND_JS, HOST_HELPERS, HOST_CASES, NOAUTH_ADD } = require("./payloads");

const MARK = "dao-one-windows";

// 每条补丁: [锚点(必须恰好出现一次), 替换文本]。锚点缺失/重复即失败, 绝不静默错插。
function buildPatches() {
  const navGithub =
    '<div class="ni" data-tab="github" onclick="sw(\'github\')" title="GitHub · 统一管理(PAT/组织/迁仓/公私/多账号舰队/GitHub MCP 同步)">🐙</div>';
  const navWindows =
    '<div class="ni" data-tab="windows" onclick="sw(\'windows\')" title="Windows · 远程桌面连接(官方 mstsc 收编)">🪟</div>';
  return [
    {
      name: "solo 白名单",
      anchor: "'mcp', 'github', 'proxy'].includes(soloBoard",
      replace: "'mcp', 'github', 'proxy', 'windows'].includes(soloBoard",
    },
    {
      name: "侧栏导航",
      anchor: navGithub,
      replace: navGithub + "\n" + navWindows,
    },
    {
      name: "tv 视图容器",
      anchor: '<div class="tv" id="v-github"></div>',
      replace:
        '<div class="tv" id="v-github"></div>\n<div class="tv" id="v-windows"></div>',
    },
    {
      name: "sw() 分发",
      anchor: "if(t==='backups'){ rBackups(); return; }",
      replace:
        "if(t==='windows'){ rWindows(); return; }\n  if(t==='backups'){ rBackups(); return; }",
    },
    {
      name: "板块渲染器(五页 mstsc 表单)",
      anchor: "usb();${_solo ?",
      replace: FRONTEND_JS + "\nusb();${_solo ?",
    },
    {
      name: "宿主 RDP 原语",
      anchor: "async function handleMiddlePanelMessage(msg, context) {",
      replace:
        HOST_HELPERS +
        "\nasync function handleMiddlePanelMessage(msg, context) {",
    },
    {
      name: "宿主消息分发",
      anchor: "    try {\n        switch (msg.command) {",
      replace: "    try {\n        switch (msg.command) {\n" + HOST_CASES,
    },
    {
      name: "免登录白名单",
      anchor: "'getProxyPanel']",
      replace: "'getProxyPanel', " + NOAUTH_ADD + "]",
    },
  ];
}

function applyPatches(source) {
  if (source.includes(MARK + " applied")) {
    throw new Error("已注入过(幂等拒绝重复注入)");
  }
  let out = source;
  for (const p of buildPatches()) {
    const n = out.split(p.anchor).length - 1;
    if (n !== 1) {
      throw new Error(
        "锚点[" + p.name + "]出现 " + n + " 次(要求恰好 1 次), 上游全能板结构已变, 需重对齐锚点"
      );
    }
    out = out.replace(p.anchor, p.replace);
  }
  return "// " + MARK + " applied\n" + out;
}

function copyTree(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const ent of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, ent.name);
    const d = path.join(dst, ent.name);
    if (ent.isDirectory()) copyTree(s, d);
    else fs.copyFileSync(s, d);
  }
}

function derive(daoOneDir, outDir) {
  const target = path.join("vendor-vsix", "out", "extension.js");
  const srcFile = path.join(daoOneDir, target);
  if (!fs.existsSync(srcFile)) {
    throw new Error("非 dao-one 安装目录(缺 " + target + "): " + daoOneDir);
  }
  copyTree(daoOneDir, outDir);
  const patched = applyPatches(fs.readFileSync(srcFile, "utf8"));
  fs.writeFileSync(path.join(outDir, target), patched, "utf8");
  // 版本 +1 patch: 装入用户 VS Code 时可与 Devin Desktop 侧的原版并存互不干扰(不同安装根)。
  const pkgFile = path.join(outDir, "package.json");
  const pkg = JSON.parse(fs.readFileSync(pkgFile, "utf8"));
  const v = String(pkg.version || "0.0.0").split(".").map((x) => parseInt(x, 10) || 0);
  v[2] += 1;
  pkg.version = v.join(".");
  pkg.description = ((pkg.description || "") + " · +🪟 Windows 板块(官方 mstsc 收编)").trim();
  fs.writeFileSync(pkgFile, JSON.stringify(pkg, null, 2), "utf8");
  return { version: pkg.version, name: pkg.name, publisher: pkg.publisher };
}

if (require.main === module) {
  const [daoOneDir, outDir] = process.argv.slice(2);
  if (!daoOneDir || !outDir) {
    console.error("用法: node inject.js <dao-one安装目录> <输出目录>");
    process.exit(2);
  }
  const info = derive(path.resolve(daoOneDir), path.resolve(outDir));
  console.log("✓ 衍生完成: " + info.publisher + "." + info.name + "@" + info.version + " → " + path.resolve(outDir));
}

module.exports = { applyPatches, derive, buildPatches, MARK };
