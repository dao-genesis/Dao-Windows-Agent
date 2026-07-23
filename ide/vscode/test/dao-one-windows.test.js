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
    "        && !route.startsWith('/i/')",
    "    if (BRIDGE_DAEMON_ROUTES.has(route)) {",
    "            const up = daoWsUpstreamFor(uurl.pathname, uurl.search || '');",
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

test("分而治之: 开桌面=顶层独立页(一账号一页 · 官方 Guacamole 引擎 · 非自造 rdpjs)", () => {
  const out = applyPatches(fixture());
  // 管理面只留 ①配置台 ②账号池 —— ③内嵌桌面模式与共享 iframe 彻底退场
  assert.ok(!out.includes("wmSwitch(&#39;desktop&#39;)"), "残留 ③ 内嵌远程桌面模式按钮");
  assert.ok(!out.includes("wdeskwrap"), "残留共享桌面容器 wdeskwrap");
  assert.ok(!out.includes("function ensureDesk("), "残留内嵌桌面 ensureDesk");
  assert.ok(!out.includes("function deskMount("), "残留内嵌桌面 deskMount");
  // 开桌面 = 交给外壳(/shell)在顶层页面栏开一张独立 iframe 页(如 Devin 多实例)
  assert.ok(out.includes("function wdeskOpen("), "缺独立页打开 wdeskOpen");
  assert.ok(out.includes("function daoWinDeskReady("), "缺 winDeskReady 独立页回执 daoWinDeskReady");
  assert.ok(out.includes("d.type==='winDeskReady'"), "缺 winDeskReady 回执处理");
  assert.ok(out.includes("daoWinDeskReady(d)"), "winDeskReady 回执未走独立页打开");
  assert.ok(out.includes("type:'open'"), "未向外壳发 type:'open' 顶层开页消息");
  assert.ok(out.includes("'wdesk:'+d.account"), "顶层页 id 未按账号隔离(wdesk:<account>)");
  assert.ok(out.includes("account='+encodeURIComponent(d.account)"), "桌面页 URL 未携带账号参数");
  assert.ok(out.includes("winDeskOpenExternal"), "缺外壳缺位时的系统浏览器兜底");
  // 管理行按钮接线: 连接档案/账号池 开桌面均带真实账号与目标
  assert.ok(out.includes("wdeskOpen(p.name,p.name"), "连接档案 开桌面未传档案目标");
  assert.ok(out.includes("wdeskOpen(a.name,a.name"), "账号池 开桌面未传账号目标");
  // .rdp 档案键 → 官方 token 会话选项直通(剪贴板/驱动器/旁观)
  assert.ok(out.includes("function wdeskOptsQ("), "缺档案键→token 选项映射 wdeskOptsQ");
  assert.ok(out.includes("clipboard=off"), "剪贴板禁用未映射 clipboard=off");
  assert.ok(out.includes("&drive="), "驱动器重定向未映射 drive=");
  assert.ok(out.includes("readonly=1"), "旁观模式未映射 readonly=1");
  // 宿主原语: 官方 Guacamole 链路(guacd + guacamole-lite 隧道), 凭据由隧道持有
  assert.ok(out.includes("function daoWinDeskEnsure("), "缺宿主 daoWinDeskEnsure");
  assert.ok(out.includes("function daoWinGuacAcctSync("), "缺隧道账号注册表登记 daoWinGuacAcctSync");
  assert.ok(out.includes("DAO_ACCOUNTS_JSON"), "隧道未接账号注册表(DAO_ACCOUNTS_JSON)");
  assert.ok(out.includes("case 'winDeskEnsure'"), "缺 case winDeskEnsure");
  assert.ok(NOAUTH_ADD.includes("winDeskEnsure"), "NOAUTH_ADD 缺 winDeskEnsure");
  assert.ok(NOAUTH_ADD.includes("winDeskOpenExternal"), "NOAUTH_ADD 缺 winDeskOpenExternal");
  assert.ok(out.includes("/desktop"), "桌面未指向隧道 /desktop 单页客户端");
  assert.ok(out.includes("guacd"), "宿主未拉起 guacd");
  // 本源护栏: 自造 node-rdpjs 路线彻底退场
  assert.ok(!out.includes("view.html?ip="), "残留旧 rdpjs view.html 路线");
  assert.ok(!out.includes("rdp_cred.json"), "残留旧 rdpjs 凭据文件路线");
  assert.ok(!out.includes("9250"), "残留旧 rdpjs 网关端口");
});

test("真机缺陷修复护栏: 同源桌面路由 / guacd 先行 / 账号池异步不阻塞 / UI 看门狗", () => {
  const out = applyPatches(fixture());
  // 缺陷#1 · 同源桌面路由: 顶层页 URL 走主口 /wdesk 反代(公网可达), 不再裸发 127.0.0.1:4824
  assert.ok(out.includes("'/wdesk/desktop'"), "winDeskEnsure 未返回同源相对地址 /wdesk/desktop");
  assert.ok(out.includes("function daoWdeskHttpProxy("), "缺 /wdesk HTTP 反代");
  assert.ok(out.includes("function daoWdeskWsProxy("), "缺 /wdesk-ws WS 反代");
  assert.ok(out.includes("route.startsWith('/wdesk/')"), "路由表未接 /wdesk 分支");
  assert.ok(out.includes("&& !route.startsWith('/wdesk')"), "/wdesk 未入免鉴权白名单");
  assert.ok(out.includes("uurl.pathname === '/wdesk-ws'"), "WS 升级未接 /wdesk-ws 分支");
  assert.ok(out.includes("localUrl"), "缺系统浏览器兜底 localUrl");
  // 缺陷#2 · 账号池: 异步 PowerShell(不阻塞宿主消息循环) + 永远回包(错误也回)
  assert.ok(out.includes("function daoPSAsync("), "缺异步 PowerShell daoPSAsync");
  assert.ok(out.includes("async function daoWinAcctList("), "daoWinAcctList 未异步化");
  assert.ok(out.includes("await daoWinAcctList()"), "winAcctList case 未 await");
  assert.ok(/catch \(e\) \{ reply\(\{ type: 'winAcctData', items: \[\], error:/.test(out), "winAcctList 异常未回包");
  // 缺陷#3 · UI 看门狗: 加载 20s 无回包即收束并提示重试
  assert.ok(out.includes("function wWatch("), "缺前端加载看门狗 wWatch");
  assert.ok(out.includes("function wWatchClear("), "缺看门狗清除 wWatchClear");
  // 缺陷#4 · guacd 先行: 不受 4824 已监听短路遮蔽
  const iEnsure = out.indexOf("async function daoWinDeskEnsure(");
  const body = out.slice(iEnsure, out.indexOf("function daoWdeskHttpProxy("));
  assert.ok(body.indexOf("guacd") < body.indexOf("daoTcpUp(DAO_TUNNEL_HTTP_PORT)"), "guacd 拉起仍在 4824 短路之后");
});

test("隧道账号注册表专用文件(win-guac-accounts.json), 绝不写 Devin ~/.dao/accounts.json", () => {
  const g = new Function(
    "path", "os", "fs",
    HOST_HELPERS + "\nreturn { daoWinGuacAcctPath };"
  )(path, require("os"), fs);
  const p = g.daoWinGuacAcctPath();
  assert.ok(/win-guac-accounts\.json$/.test(p), "隧道注册表未用专用文件: " + p);
  assert.ok(!/[\\/]accounts\.json$/.test(p), "隧道注册表复用了 Devin 登录态 accounts.json");
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

test("账号池注册表专用文件, 绝不复用/覆盖 Devin ~/.dao/accounts.json(登录态)", () => {
  const reg = new Function(
    "path", "os", "fs",
    HOST_HELPERS + "\nreturn { daoWinAcctRegPath, daoWinAcctReg };"
  )(path, require("os"), fs);
  const p = reg.daoWinAcctRegPath();
  assert.ok(/win-rdp-accounts\.json$/.test(p), "注册表未用专用文件 win-rdp-accounts.json: " + p);
  assert.ok(!/[\\/]accounts\.json$/.test(p), "注册表复用了 Devin 登录态 accounts.json(会污染并覆盖 token 存储)");
  // 守卫: 标量键(如 devinToken)一律忽略, 仅收账号对象; 防误读非本表 JSON 污染账号列
  assert.ok(HOST_HELPERS.includes("typeof j[k] === 'object'"), "daoWinAcctReg 缺非对象条目过滤守卫");
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
