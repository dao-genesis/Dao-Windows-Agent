"use strict";
// dao-one-windows · 衍生注入器护栏 — 本源: Windows 是原 dao-one/9920 全能板的同级 tab,
// 不是任何自建面板; 注入负载与官方 mstsc 五页/.rdp 键 1:1。
const test = require("node:test");
const assert = require("node:assert");
const path = require("path");
const fs = require("fs");

const { applyPatches, buildPatches, MARK } = require("../dao-one-windows/inject");
const { FRONTEND_JS, HOST_HELPERS, HOST_CASES, NOAUTH_ADD } = require("../dao-one-windows/payloads");

// 迷你真源夹具: 只含全部锚点(锚点即上游全能板结构契约; 上游变了这里先红)。
function fixture() {
  return [
    "const _solo = ['overview', 'switch', 'bridge', 'backups', 'inject', 'mcp', 'github', 'proxy'].includes(soloBoard || '') ? soloBoard : '';",
    '<div class="ni" data-tab="github" onclick="sw(\'github\')" title="GitHub · 统一管理(PAT/组织/迁仓/公私/多账号舰队/GitHub MCP 同步)">🐙</div>',
    '<div class="tv" id="v-github"></div>',
    "  if(t==='backups'){ rBackups(); return; }",
    "usb();${_solo ? `try{sw('${_solo}')}catch(e){rc()}` : 'rc()'};",
    "async function handleMiddlePanelMessage(msg, context) {",
    "    try {",
    "        switch (msg.command) {",
    "'getProxyPanel']",
  ].join("\n");
}

test("注入后包含 Windows tab 全链路(白名单/导航/视图/分发/渲染器/宿主原语)", () => {
  const out = applyPatches(fixture());
  assert.ok(out.startsWith("// " + MARK + " applied"));
  assert.ok(out.includes("'proxy', 'windows'].includes(soloBoard"));
  assert.ok(out.includes('data-tab="windows"'));
  assert.ok(out.includes('<div class="tv" id="v-windows"></div>'));
  assert.ok(out.includes("if(t==='windows'){ rWindows(); return; }"));
  assert.ok(out.includes("function rWindows()"));
  assert.ok(out.includes("case 'winRdpList'"));
  assert.ok(out.includes("function daoWinRdpFileContent"));
  assert.ok(out.includes("'getProxyPanel', " + NOAUTH_ADD + "]"));
});

test("归一两模块外壳: ① 统一配置管理台 / ② 账号池(仿切号板) 收敛于 Windows 板块", () => {
  const out = applyPatches(fixture());
  // 外壳双模块切换
  assert.ok(out.includes("function wmSwitch("), "缺模块切换 wmSwitch");
  assert.ok(out.includes("wmSwitch(&#39;config&#39;)"), "缺 ① 配置台切换按钮");
  assert.ok(out.includes("wmSwitch(&#39;pool&#39;)"), "缺 ② 账号池切换按钮");
  // 模块① 配置台仍是官方五页连接档案
  assert.ok(out.includes("function rWinConfig("), "缺模块① 渲染器 rWinConfig");
  assert.ok(out.includes("function wrForm("), "缺官方五页表单 wrForm");
  // 模块② 账号池渲染器 + 建号/删号/注销/开桌面
  assert.ok(out.includes("function rWinPool("), "缺模块② 渲染器 rWinPool");
  assert.ok(out.includes("function waCreate("), "缺建号 waCreate");
  assert.ok(out.includes("function waDel("), "缺删号 waDel");
  assert.ok(out.includes("function waLogoff("), "缺注销会话 waLogoff");
  assert.ok(out.includes("function waOpenDesk("), "缺账号开桌面 waOpenDesk");
});

test("账号池宿主原语(多 Windows 账号生命周期 · 白名单/case/PowerShell 原语)", () => {
  const out = applyPatches(fixture());
  ["winAcctList", "winAcctCreate", "winAcctDestroy", "winAcctLogoff"].forEach((c) => {
    assert.ok(NOAUTH_ADD.includes(c), "NOAUTH_ADD 缺 " + c);
    assert.ok(out.includes("case '" + c + "'"), "缺 case " + c);
  });
  assert.ok(out.includes("function daoWinAcctList("), "缺宿主 daoWinAcctList");
  assert.ok(out.includes("function daoWinAcctCreate("), "缺宿主 daoWinAcctCreate");
  assert.ok(out.includes("function daoWinAcctDestroy("), "缺宿主 daoWinAcctDestroy");
  assert.ok(out.includes("New-LocalUser"), "建号未走 New-LocalUser");
  assert.ok(out.includes("Remote Desktop Users"), "建号未加入 Remote Desktop Users");
  assert.ok(out.includes("Remove-LocalUser"), "删号未走 Remove-LocalUser");
  assert.ok(out.includes("d.type==='winAcctData'"), "缺 winAcctData 回执处理");
});

test("开桌面=独立顶层板块(动态平级 tab · 非内嵌 Windows 子标签)", () => {
  const out = applyPatches(fixture());
  // 动态桌面板块创建/关闭
  assert.ok(out.includes("function wdSpawn("), "缺独立桌面板块 wdSpawn");
  assert.ok(out.includes("function wdClose("), "缺桌面板块关闭 wdClose");
  assert.ok(out.includes("'wdesk-'+(++WDESK.seq)"), "桌面板块未生成平级 tab id");
  // sw() 分发放行 wdesk- 动态板块
  assert.ok(out.includes("t.indexOf('wdesk-')===0"), "sw() 未放行 wdesk- 动态板块");
  // winRdpEmbed 回执改为拉起独立板块(不再内嵌)
  assert.ok(out.includes("wdSpawn(d.url,d.label)"), "winRdpEmbed 回执未拉起独立桌面板块");
  // 本源护栏: 不再把桌面 iframe 内嵌进 Windows 板块(v-windows)自身
  assert.ok(!out.includes("function wrGoEmbed("), "残留旧内嵌 wrGoEmbed");
  assert.ok(!out.includes("var WEMB="), "残留旧内嵌态 WEMB");
  // 开桌面走网关 view.html(单目标 canvas), 服务端持凭据不下发浏览器
  assert.ok(out.includes("view.html?ip="), "桌面未指向 view.html 单目标视图");
  assert.ok(out.includes("rdp_cred.json"), "网关未从服务端凭据文件取凭据");
});

test("幂等: 已注入的源拒绝二次注入", () => {
  const out = applyPatches(fixture());
  assert.throws(() => applyPatches(out), /已注入过/);
});

test("锚点缺失即失败(绝不静默错插)", () => {
  assert.throws(() => applyPatches("nothing here"), /锚点/);
});

test("前端负载不得破坏模板字面量(禁反引号/禁 ${ 序列)且自身语法合法", () => {
  assert.ok(!FRONTEND_JS.includes("`"), "前端负载含反引号");
  assert.ok(!FRONTEND_JS.includes("${"), "前端负载含 ${");
  assert.ok(!FRONTEND_JS.includes("</script"), "前端负载含 </script");
  // 语法检查(浏览器侧脚本)
  new Function(FRONTEND_JS + "\n;function esc(s){return s}function cmd(){}function toast(){}var S={tab:''};");
});

test("宿主 .rdp 键映射与本仓 rdpFileContent 完全一致(官方语义单一真源)", () => {
  // 从注入负载中取出 daoWinRdpFileContent 并实例化
  const fn = new Function(
    "path", "os", "fs",
    HOST_HELPERS + "\nreturn daoWinRdpFileContent;"
  )(path, require("os"), fs);
  const ext = fs.readFileSync(path.join(__dirname, "..", "extension.js"), "utf8");
  const m = ext.match(/function rdpFileContent\(p\) \{[\s\S]*?\n\}/);
  assert.ok(m, "extension.js 缺 rdpFileContent");
  const ref = new Function(m[0] + "\nreturn rdpFileContent;")();
  const samples = [
    {},
    { host: "pc.example.com", port: "3390", username: "u", savecred: true },
    { fullscreen: false, width: 1280, height: 720, bpp: 16, multimon: true, connbar: false },
    { audiomode: 2, audiocapture: 1, keyboardhook: 0, clipboard: false, printers: true, smartcards: false, ports: true, drives: true, pnp: true },
    { conntype: 4, wallpaper: false, fontsmoothing: true, composition: true, fullwindowdrag: true, menuanims: true, themes: false, bitmapcache: false, autoreconnect: false },
    { authlevel: 0, gwmethod: "manual", gateway: "gw.example.com", gwbypass: false, gwcreds: false },
    { gwmethod: "none" },
  ];
  for (const s of samples) assert.strictEqual(fn(s), ref(s), JSON.stringify(s));
});

test("补丁表锚点在真源快照上唯一(有快照时)", () => {
  const snap = "/home/ubuntu/dao_one_2_28_14/vendor-vsix-out-extension.js";
  if (!fs.existsSync(snap)) return; // CI 无快照, 本地/实机衍生时验证
  const src = fs.readFileSync(snap, "utf8");
  for (const p of buildPatches()) {
    assert.strictEqual(src.split(p.anchor).length - 1, 1, "锚点不唯一: " + p.name);
  }
});

test("架构护栏: 本仓不再贡献自建 dao.unified/dao.proxyPro 视图, 归一主页指向 dao-one 本源", () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
  const views = JSON.stringify(pkg.contributes.views || {});
  assert.ok(!views.includes("dao.unified"), "package.json 仍贡献 dao.unified 视图");
  assert.ok(!views.includes("dao.proxyPro"), "package.json 仍贡献 dao.proxyPro 视图");
  const cmds = (pkg.contributes.commands || []).map((c) => c.command);
  assert.ok(!cmds.includes("dao.unified.open"), "package.json 仍贡献 dao.unified.open 命令");
  const ext = fs.readFileSync(path.join(__dirname, "..", "extension.js"), "utf8");
  assert.ok(ext.includes('executeCommand("dao.openCloudPanel")'), "openHome 未指向 dao-one 全能板");
  assert.ok(ext.includes("unified: false"), "dao-ai-base 仍默认自建归一面板");
});
