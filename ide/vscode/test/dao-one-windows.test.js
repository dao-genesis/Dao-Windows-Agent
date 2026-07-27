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
  // 桌面页 URL 必须以本页自身源绝对化(webview 外壳无法解析相对地址 → 白屏), 且非 http(s) 源回退 localUrl
  assert.ok(out.includes("new URL(u,location.href)"), "桌面页 URL 未按本页源绝对化(webview 白屏根因)");
  assert.ok(/protocol==='http:'\|\|au\.protocol==='https:'/.test(out), "非 http(s) 源未回退 localUrl");
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
  // 官方五页(显示/本地资源/体验)全量直通面板内桌面: mstsc 同义配置 → Guacamole 官方参数
  assert.ok(out.includes("&colordepth="), "色深(bpp)未映射 colordepth");
  assert.ok(out.includes("&wallpaper="), "桌面背景未映射 wallpaper");
  assert.ok(out.includes("&theming="), "视觉样式未映射 theming");
  assert.ok(out.includes("&fontsmoothing="), "字体平滑未映射 fontsmoothing");
  assert.ok(out.includes("&windowdrag="), "拖拉显示窗口内容未映射 windowdrag");
  assert.ok(out.includes("&composition="), "桌面布局未映射 composition");
  assert.ok(out.includes("&animations="), "菜单窗口动画未映射 animations");
  assert.ok(out.includes("&bitmapcache="), "位图缓存未映射 bitmapcache");
  assert.ok(out.includes("audio=off") && out.includes("audio=both"), "远程音频/录音未映射 audio");
  assert.ok(out.includes("&printing="), "打印机未映射 printing");
  // 连接档案「开桌面」把整份五页档案原样递给映射器(非仅剪贴板/驱动器两键)
  assert.ok(/wdeskOpen\(p\.name,p\.name,\{[^}]*\},p\)/.test(out), "开桌面未传整份五页档案");
  // 五页映射语义抽检(实例化前端负载中的 wdeskOptsQ 纯函数)
  const q = new Function("var window={addEventListener:function(){}};var document={getElementById:function(){return null;}};\n" + FRONTEND_JS + "\n;return wdeskOptsQ;\nfunction esc(s){return s}function cmd(){}function toast(){}var S={tab:''};")();
  assert.strictEqual(q(null), "");
  const full = q({ bpp: "16", wallpaper: false, themes: false, fontsmoothing: true, fullwindowdrag: true, composition: true, menuanims: true, bitmapcache: false, audiomode: "2", printers: true, clipboard: false, drives: true });
  ["colordepth=16", "wallpaper=0", "theming=0", "fontsmoothing=1", "windowdrag=1", "composition=1", "animations=1", "bitmapcache=0", "audio=off", "printing=1", "clipboard=off", "&drive="].forEach((s) => assert.ok(full.includes(s), "五页直通缺 " + s));
  assert.ok(q({ audiomode: "0", audiocapture: "1" }).includes("audio=both"), "录音未映射 audio=both");
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

test("负载签名护栏: 首行标记携带 sig, 供再注入器判定「已注入但过时」", () => {
  const { APPLIED_TAG, PAYLOAD_SIG } = require("../dao-one-windows/inject");
  // sig 为 16 位十六进制内容哈希, 负载任一半变化即变
  assert.match(PAYLOAD_SIG, /^[0-9a-f]{16}$/, "PAYLOAD_SIG 非 16 位 hex");
  assert.strictEqual(APPLIED_TAG, MARK + " applied sig=" + PAYLOAD_SIG);
  const out = applyPatches(fixture());
  assert.ok(out.startsWith("// " + APPLIED_TAG), "首行未携带当前 sig");
  // 三态: 未注入 / 已注入且最新(含 APPLIED_TAG) / 已注入但过时(有 MARK 无当前 sig)
  assert.ok(!fixture().includes(MARK + " applied"), "真源夹具不应含 MARK");
  assert.ok(out.includes(MARK + " applied"), "注入产物应含 MARK");
  // 过时样例(旧 sig)既含 MARK 又不含当前 APPLIED_TAG → 再注入器应判为过时
  const staleSample = "// " + MARK + " applied sig=deadbeefdeadbeef\nsome old injected body";
  assert.ok(staleSample.includes(MARK + " applied"), "过时样例应含 MARK");
  assert.ok(!staleSample.includes(APPLIED_TAG), "过时样例不应含当前 sig");
});

test("再注入器双宿主护栏: 扫 ~/.vscode 与 ~/.devin 两处, 且候选重载端口含 9925", () => {
  const rj = require("../dao-one-windows/reinject");
  assert.deepStrictEqual(rj.EXT_ROOTS, [".vscode", ".devin"], "EXT_ROOTS 缺双宿主");
  assert.ok(rj.RELOAD_PORTS.includes(9920) && rj.RELOAD_PORTS.includes(9925), "重载端口缺 9920/9925");
  assert.deepStrictEqual(rj.verKey("dao.dao-one-2.29.11"), [2, 29, 11]);
  assert.ok(rj.cmp(rj.verKey("dao.dao-one-2.29.11"), rj.verKey("dao.dao-one-2.29.9")) > 0, "版本比较错");
  assert.ok(Array.isArray(rj.daoOneTargets()), "daoOneTargets 应返回数组(缺目录时守柔)");
});

test("前端负载不得破坏模板字面量(禁反引号/禁 ${ 序列)且自身语法合法", () => {
  assert.ok(!FRONTEND_JS.includes("`"), "前端负载含反引号");
  assert.ok(!FRONTEND_JS.includes("${"), "前端负载含 ${");
  assert.ok(!FRONTEND_JS.includes("</script"), "前端负载含 </script");
  // 语法检查(浏览器侧脚本)
  new Function(FRONTEND_JS + "\n;function esc(s){return s}function cmd(){}function toast(){}var S={tab:''};");
});

test("宿主 .rdp 键映射覆盖官方 mstsc 五页标准键(单一真源在注入负载)", () => {
  // 从注入负载中取出 daoWinRdpFileContent 并实例化(负载即 .rdp 语义唯一真源)
  const fn = new Function(
    "path", "os", "fs",
    HOST_HELPERS + "\nreturn daoWinRdpFileContent;"
  )(path, require("os"), fs);
  const out = fn({ host: "pc.example.com", port: "3390", username: "u" });
  // 常规/显示/本地资源/体验/高级 五页对应的官方标准键
  for (const key of [
    "full address:s:pc.example.com:3390", "username:s:u",
    "screen mode id:i:", "desktopwidth:i:", "desktopheight:i:", "session bpp:i:",
    "use multimon:i:", "displayconnectionbar:i:",
    "audiomode:i:", "audiocapturemode:i:", "keyboardhook:i:", "redirectclipboard:i:",
    "redirectprinters:i:", "redirectsmartcards:i:", "redirectcomports:i:", "drivestoredirect:s:",
    "connection type:i:", "disable wallpaper:i:", "allow font smoothing:i:",
    "allow desktop composition:i:", "disable full window drag:i:", "disable menu anims:i:",
    "disable themes:i:", "bitmapcachepersistenable:i:", "autoreconnection enabled:i:",
    "authentication level:i:", "gatewayhostname:s:", "gatewayusagemethod:i:",
  ]) assert.ok(out.includes(key), ".rdp 缺官方键 " + key);
  // 官方 mstsc 出厂默认对齐(空档案=官方空白对话框语义)
  const dflt = fn({});
  assert.ok(dflt.startsWith("full address:s:\r\n"), "默认地址应为空(官方空白对话框)");
  assert.ok(dflt.includes("screen mode id:i:2"), "默认全屏 screen mode id 2");
  assert.ok(dflt.includes("authentication level:i:2"), "默认认证级别 2");
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

test("架构护栏: 本源唯一 — dao-one(devin-remote) 是唯一基底, 本仓不再自建任何插件前端", () => {
  const IDE = path.join(__dirname, "..");
  // 漂移产物必须退役: 独立插件本体/独立主页/另一支归一系(dao-cascade)面板
  for (const drift of ["extension.js", "win-home.js", "package.json", "dao-ai-base", "unify.js"]) {
    assert.ok(!fs.existsSync(path.join(IDE, drift)), "漂移产物未清理: ide/vscode/" + drift);
  }
  // 唯一交付 = 上游 dao-one 构建 + dao-one-windows 注入 + 打包
  const sh = fs.readFileSync(path.join(IDE, "build.sh"), "utf8");
  assert.ok(sh.includes("devin-remote"), "build.sh 应从 devin-remote 真源构建 dao-one");
  assert.ok(sh.includes("dao-one-windows/inject.js"), "build.sh 应经 dao-one-windows 注入 🪟 板块");
  assert.ok(sh.includes("pack_vsix.py"), "build.sh 应用 pack_vsix.py 打 VSIX");
});
