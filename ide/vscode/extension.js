"use strict";
// DAO Windows Agent · VSCode 前端（正本清源·路线A 桌面级路由）
//
// 本源：IDE 装上本插件 → 面板里直接就是整台 Windows 的桌面本体。
// 每个 IDE 窗口 = 一路独立完整的 RDP 会话（类多 RDP 的一路），
// canvas 渲染进 Webview，鼠键直操，不是投屏截图流。
//
// 旧的按钮/文字面板（控制面）降级为辅助自动化后端。
const vscode = require("vscode");
const http = require("http");
const cp = require("child_process");
const path = require("path");
const crypto = require("crypto");
const fs = require("fs");

let output;
let statusItem;
let panel;           // 旧控制面板（降级为辅助）
const desktopPanels = new Map(); // key(账号名或 ide_<hash>) → 桌面路由面板（每账号一路独立桌面）
let spawnedBridge = null;
let activeBridgeUrl = null;
let _ideTools = null;  // vscode_* IDE 对等面子插件宿主

function cfg() {
  const c = vscode.workspace.getConfiguration("daoWin");
  return {
    bridgeUrl: (c.get("bridgeUrl") || "http://127.0.0.1:9920").replace(/\/$/, ""),
    token: c.get("token") || "",
    autostart: c.get("autostart") !== false,
    pythonPath: c.get("pythonPath") || "python",
    tunnelHttpUrl: (c.get("tunnelHttpUrl") || "http://127.0.0.1:4824").replace(/\/$/, ""),
    tunnelWsPort: parseInt(c.get("tunnelWsPort") || "4823", 10),
  };
}

// —— 子插件自动收编（樸散為器·道并行而不相悖）——
// 任一同装的 DAO 领域子插件在其 package.json 声明 `daoSubplugin`（或 contributes.daoSubplugin），
// 本插件启动即把它落成发现目录里的描述符 → 机控桥扫描后自动多出一路 @ 工作层（无需改框架）。
function subpluginDir() {
  return path.join(require("os").homedir(), ".dao", "subplugins");
}

function harvestSubplugins(vendorRoot) {
  let dir;
  try {
    dir = subpluginDir();
    fs.mkdirSync(dir, { recursive: true });
  } catch (e) { log("子插件发现目录创建失败: " + e.message); return 0; }
  // 收编源 = 同装 VS Code 扩展 ∪ 折入 vendor/ 的二合一子模块（后者不在 vscode.extensions.all）。
  const sources = [];
  for (const ext of vscode.extensions.all) sources.push({ id: "vscode:" + ext.id, pj: ext.packageJSON || {} });
  if (vendorRoot) {
    let names = [];
    try { names = fs.readdirSync(vendorRoot); } catch (_) {}
    for (const nm of names) {
      try {
        const pj = JSON.parse(fs.readFileSync(path.join(vendorRoot, nm, "package.json"), "utf-8"));
        sources.push({ id: "vendor:" + nm, pj });
      } catch (_) {}
    }
  }
  let n = 0;
  for (const src of sources) {
    const pj = src.pj;
    const spec = pj.daoSubplugin || (pj.contributes && pj.contributes.daoSubplugin);
    if (!spec || !spec.app_id || !Array.isArray(spec.verbs) || !spec.verbs.length) continue;
    const desc = Object.assign({ source: src.id, layer: "domain" }, spec);
    if (!desc.invoke_url) { log("子插件 " + src.id + " 缺 invoke_url，跳过"); continue; }
    try {
      fs.writeFileSync(path.join(dir, desc.app_id + ".json"), JSON.stringify(desc, null, 2), "utf-8");
      n++;
      log("收编子插件 @" + (desc.mention || desc.app_id) + " ← " + src.id);
    } catch (e) { log("写子插件描述符失败 " + src.id + ": " + e.message); }
  }
  return n;
}

// 本 IDE 窗口的稳定 session id：绑定工作区路径（同一窗口=同一隔离会话），无工作区则随机。
function windowSessionId() {
  const ws = vscode.workspace.workspaceFolders;
  const seed = ws && ws.length ? ws[0].uri.fsPath : ("nows-" + process.pid);
  const h = crypto.createHash("sha1").update(seed).digest("hex").slice(0, 8);
  return "ide_" + h;
}

// —— HTTP 客户端（纯 node，无第三方依赖）——
function apiCall(base, token, method, apiPath, body, timeoutMs) {
  return new Promise((resolve, reject) => {
    let u;
    try { u = new URL(base + apiPath); } catch (e) { return reject(e); }
    const data = body ? Buffer.from(JSON.stringify(body), "utf8") : null;
    const headers = { "Content-Type": "application/json; charset=utf-8" };
    if (token) headers["Authorization"] = "Bearer " + token;
    if (data) headers["Content-Length"] = data.length;
    const req = http.request(
      { hostname: u.hostname, port: u.port || 80, path: u.pathname + u.search, method, headers },
      (res) => {
        let chunks = [];
        res.on("data", (d) => chunks.push(d));
        res.on("end", () => {
          const raw = Buffer.concat(chunks).toString("utf8");
          let parsed;
          try { parsed = raw ? JSON.parse(raw) : {}; } catch (e) { parsed = { raw }; }
          resolve({ status: res.statusCode, body: parsed });
        });
      }
    );
    req.on("error", reject);
    req.setTimeout(timeoutMs || 15000, () => { req.destroy(new Error("请求超时 " + apiPath)); });
    if (data) req.write(data);
    req.end();
  });
}

function log(msg) {
  if (!output) output = vscode.window.createOutputChannel("DAO Windows Agent");
  const ts = new Date().toISOString().slice(11, 19);
  output.appendLine(`[${ts}] ${msg}`);
}

async function tryHealth(base, token) {
  try {
    const r = await apiCall(base, token, "GET", "/api/health", null, 4000);
    return r.status === 200 && r.body && r.body.ok === true;
  } catch (e) { return false; }
}

// 连不上配置桥且开启 autostart → 用插件自带 runtime 起本地桥（零配置冷启动）。
async function ensureBridge(context) {
  const c = cfg();
  if (await tryHealth(c.bridgeUrl, c.token)) {
    activeBridgeUrl = c.bridgeUrl;
    log("已连上机控桥: " + activeBridgeUrl);
    return { url: activeBridgeUrl, token: c.token, spawned: false };
  }
  if (!c.autostart) {
    log("桥连不上且未开启 autostart: " + c.bridgeUrl);
    return null;
  }
  // 已自启且活着
  if (activeBridgeUrl && (await tryHealth(activeBridgeUrl, c.token))) {
    return { url: activeBridgeUrl, token: c.token, spawned: true };
  }
  const runtime = path.join(context.extensionPath, "runtime");
  const port = 9930;
  const localUrl = "http://127.0.0.1:" + port;
  log("桥连不上，用自带 runtime 自启本地桥 @ " + localUrl);
  try {
    spawnedBridge = cp.spawn(
      c.pythonPath,
      ["-m", "bridge.server", "--host", "127.0.0.1", "--port", String(port), "--token", c.token],
      { cwd: runtime, env: Object.assign({}, process.env, { DAO_WIN_TOKEN: c.token }), windowsHide: true }
    );
    spawnedBridge.stdout.on("data", (d) => log("[bridge] " + String(d).trim()));
    spawnedBridge.stderr.on("data", (d) => log("[bridge!] " + String(d).trim()));
    spawnedBridge.on("exit", (code) => { log("自启桥退出 code=" + code); spawnedBridge = null; });
  } catch (e) {
    log("自启桥失败: " + e.message);
    return null;
  }
  // 轮询等待就绪
  for (let i = 0; i < 20; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (await tryHealth(localUrl, c.token)) {
      activeBridgeUrl = localUrl;
      log("自启桥就绪: " + localUrl);
      return { url: localUrl, token: c.token, spawned: true };
    }
  }
  log("自启桥超时未就绪");
  return null;
}

function setStatus(text, tooltip) {
  if (!statusItem) {
    statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    statusItem.command = "daoWin.openDesktop";
    statusItem.show();
  }
  statusItem.text = "$(vm) DAO " + text;
  statusItem.tooltip = tooltip || "DAO Windows Agent · 本窗口=隔离会话";
}

// —— 模式切换（提示词覆盖 + 工具面裁剪；态经桥持久化到 ~/.dao/mode.json 供同装插件联动）——
let modeStatusItem;
function setModeStatus(mode) {
  if (!modeStatusItem) {
    modeStatusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
    modeStatusItem.command = "daoWin.switchMode";
    modeStatusItem.show();
  }
  modeStatusItem.text = "$(settings-gear) " + (mode && mode.name ? mode.name : "\u6a21\u5f0f");
  modeStatusItem.tooltip = mode && mode.summary ? mode.summary : "DAO \u6a21\u5f0f\u5207\u6362";
}

async function switchMode(context) {
  const info = await ensureBridge(context);
  if (!info) { vscode.window.showErrorMessage("DAO: \u673a\u63a7\u6865\u4e0d\u53ef\u8fbe\uff0c\u65e0\u6cd5\u5207\u6362\u6a21\u5f0f"); return; }
  let r;
  try { r = await apiCall(info.url, info.token, "GET", "/api/mode.list"); } catch (e) {
    vscode.window.showErrorMessage("DAO: \u53d6\u6a21\u5f0f\u6e05\u5355\u5931\u8d25 " + e.message); return;
  }
  const modes = (r.body && r.body.modes) || [];
  const current = r.body && r.body.current;
  const items = modes.map((m) => ({
    label: (m.mode_id === current ? "$(check) " : "") + m.name,
    description: m.mode_id,
    detail: m.summary,
    modeId: m.mode_id,
  }));
  const sel = await vscode.window.showQuickPick(items, { placeHolder: "\u5207\u6362 DAO \u6a21\u5f0f\uff08\u63d0\u793a\u8bcd\u8986\u76d6 + \u5de5\u5177\u9762\u88c1\u526a\uff09" });
  if (!sel || sel.modeId === current) return;
  try {
    const res = await apiCall(info.url, info.token, "POST", "/api/mode.set", { mode: sel.modeId });
    if (res.body && res.body.error) { vscode.window.showErrorMessage("DAO: " + res.body.error); return; }
    const mode = res.body && res.body.current;
    setModeStatus(mode);
    vscode.window.showInformationMessage("DAO \u6a21\u5f0f\u5df2\u5207\u6362: " + (mode ? mode.name : sel.modeId));
  } catch (e) {
    vscode.window.showErrorMessage("DAO: \u5207\u6362\u6a21\u5f0f\u5931\u8d25 " + e.message);
  }
}

async function refreshModeStatus(context, info) {
  try {
    const r = await apiCall(info.url, info.token, "GET", "/api/mode.get");
    if (r.body && r.body.current) setModeStatus(r.body.current);
  } catch (e) { /* 桥未就绪时静默，切换命令仍可用 */ }
}

// —— 令牌铸造 HTTP 取账号清单（供 QuickPick / 面板下拉）——
function fetchAccounts(tunnelHttpUrl) {
  return new Promise((resolve) => {
    let u;
    try { u = new URL(tunnelHttpUrl + "/accounts"); } catch (e) { return resolve([]); }
    const req = http.request({ hostname: u.hostname, port: u.port || 80, path: u.pathname, method: "GET" }, (res) => {
      let chunks = [];
      res.on("data", (d) => chunks.push(d));
      res.on("end", () => {
        try { resolve((JSON.parse(Buffer.concat(chunks).toString("utf8")) || {}).accounts || []); }
        catch (e) { resolve([]); }
      });
    });
    req.on("error", () => resolve([]));
    req.setTimeout(4000, () => { req.destroy(); resolve([]); });
    req.end();
  });
}

// —— 桌面路由面板（主前端：guacamole-common-js canvas → WS 隧道 → guacd → RDP 会话）——
// account 非空=按账号路由（多账号类虚拟机·扩展本源）；否则按 ide_<hash>（向后兼容）。
function desktopHtml(webview, context, sessionId, account, tunnelHttpUrl, tunnelWsPort, accounts) {
  const guacUri = webview.asWebviewUri(vscode.Uri.joinPath(context.extensionUri, "media", "guacamole-common.min.js"));
  const cspSource = webview.cspSource;
  // 隧道主机由 tunnelHttpUrl 推导（自适应任意环境：本机 127.0.0.1 / 宿主 10.0.2.2 / 局域网 IP / 公网）。
  let tunnelHost = "127.0.0.1";
  try { tunnelHost = new URL(tunnelHttpUrl).hostname || tunnelHost; } catch (e) {}
  const connectSrc = [
    "ws://" + tunnelHost + ":*", "wss://" + tunnelHost + ":*",
    "http://" + tunnelHost + ":*", "https://" + tunnelHost + ":*",
    "ws://127.0.0.1:*", "http://127.0.0.1:*", "ws://localhost:*", "http://localhost:*",
  ].join(" ");
  const cspSrc = "default-src 'none'; script-src 'unsafe-inline' " + cspSource + "; style-src 'unsafe-inline'; connect-src " + connectSrc + "; img-src data:;";
  return `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${cspSrc}">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{overflow:hidden;background:#1a1a1e;color:#e0e0e0;font-family:var(--vscode-font-family);height:100vh;display:flex;flex-direction:column}
#bar{padding:4px 10px;background:#24242a;display:flex;align-items:center;gap:8px;font-size:12px;border-bottom:1px solid #333;flex-shrink:0}
#bar button{padding:3px 8px;border:none;border-radius:3px;background:var(--vscode-button-background,#3c8dbc);color:var(--vscode-button-foreground,#fff);cursor:pointer;font-size:11px}
#tabs{display:flex;gap:4px;align-items:center;overflow-x:auto;max-width:45%}
.tab{padding:2px 8px;border-radius:3px;background:#333;cursor:pointer;white-space:nowrap;display:flex;align-items:center;gap:5px;font-size:11px;border:1px solid transparent}
.tab.on{background:#2a4a63;border-color:#3c8dbc}
.tab .dot{width:7px;height:7px;border-radius:50%;background:#999;flex-shrink:0}
.tab .x{opacity:.5;cursor:pointer;padding:0 1px}
.tab .x:hover{opacity:1;color:#ff6666}
#status{flex:1;text-align:right;opacity:.7}
#desktop{flex:1;overflow:hidden;position:relative}
.inst{position:absolute;top:0;left:0;right:0;bottom:0;display:none}
.inst.on{display:block}
.inst>div{position:absolute!important;top:0;left:0}
#overlay{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;font-size:14px;opacity:.6}
</style></head><body>
<div id="bar">
  <b>\u2630 DAO \u684c\u9762</b>
  <select id="acct" title="\u8d26\u53f7\uff08\u591a RDP \u4e00\u8def\u4e00\u684c\u9762\uff09" onchange="onAcctChange()"></select>
  <div id="tabs"></div>
  <button onclick="addInstance()" title="\u540c\u8d26\u53f7\u518d\u5f00\u4e00\u8def\u72ec\u7acb\u684c\u9762\u4f1a\u8bdd\uff08\u591a RDP \u5206\u8eab\uff0c\u5e76\u884c\u4e92\u4e0d\u5e72\u6270\uff09">\uff0b\u5206\u8eab</button>
  <button onclick="doConnect()">\u8fde\u63a5</button>
  <button onclick="doDisconnect()">\u65ad\u5f00</button>
  <button onclick="doFullscreen()">\u2922</button>
  <span id="status">\u672a\u8fde\u63a5</span>
</div>
<div id="desktop"><div id="overlay">\u70b9\u51fb\u300c\u8fde\u63a5\u300d\u5373\u53ef\u770b\u5230 Windows \u684c\u9762\uff1b\u300c\uff0b\u5206\u8eab\u300d\u53ef\u5728\u672c\u7a97\u53e3\u5185\u5e76\u884c\u591a\u8def\u684c\u9762</div></div>
<script src="${guacUri}"></script>
<script>
const TUNNEL_HTTP = ${JSON.stringify(tunnelHttpUrl)};
const TUNNEL_WS_PORT = ${tunnelWsPort};
const IDE_SESSION = ${JSON.stringify(sessionId)};
const ACCOUNT = ${JSON.stringify(account)};
const ACCOUNTS = ${JSON.stringify(accounts || [])};
const vscodeApi = acquireVsCodeApi();
const container = document.getElementById('desktop');
const statusEl = document.getElementById('status');
const acctEl = document.getElementById('acct');
const tabsEl = document.getElementById('tabs');
const MAX_RETRIES = 5;

// \u591a\u5b9e\u4f8b\u5206\u8eab\uff1a\u4e00\u4e2a IDE \u7a97\u53e3\u5185\u5e76\u884c\u591a\u8def\u540c\u8d26\u53f7\u72ec\u7acb\u684c\u9762\u4f1a\u8bdd\uff08\u7c7b\u591a RDP\uff09\u3002
// \u6bcf\u8def\u5206\u8eab = \u72ec\u7acb Guacamole client + \u72ec\u7acb\u753b\u5e03\uff1b\u952e\u76d8/\u526a\u8d34\u677f\u53ea\u8def\u7531\u5230\u6d3b\u52a8\u5206\u8eab\u3002
let instances = [];   // {id, label, el, client, display, connecting, userDisconnected, retries, retryTimer, state}
let activeId = null;
let nextId = 1;
let lastLocalClip = null;
let lastRemoteClip = null;

(function initAccounts(){
  var names = (ACCOUNTS && ACCOUNTS.length) ? ACCOUNTS.map(function(a){return a.name;}) : [];
  if (ACCOUNT && names.indexOf(ACCOUNT) < 0) names.unshift(ACCOUNT);
  if (!names.length) { acctEl.style.display='none'; return; }
  acctEl.innerHTML = names.map(function(n){
    return '<option value="'+n+'"'+(n===ACCOUNT?' selected':'')+'>'+n+'</option>';
  }).join('');
})();
function onAcctChange(){
  var sel = acctEl.value;
  if (sel === ACCOUNT) return;
  vscodeApi.postMessage({type:'openAccount', account: sel});
  acctEl.value = ACCOUNT;
}

function active(){ for (var i=0;i<instances.length;i++) if (instances[i].id===activeId) return instances[i]; return null; }
function setStatus(t, c) { statusEl.textContent = t; statusEl.style.color = c || '#e0e0e0'; }
function stateColor(s){ return ['#999','#ffcc00','#ffcc00','#44ff44','#ff8800','#ff4444'][s] || '#999'; }
function showActiveStatus(){
  var it = active(); if (!it) { setStatus('\u672a\u8fde\u63a5'); return; }
  var names = ['\u7a7a\u95f2','\u6b63\u5728\u8fde\u63a5...','\u7b49\u5f85\u4e2d...','\u5df2\u8fde\u63a5 \u25cf','\u6b63\u5728\u65ad\u5f00...','\u5df2\u65ad\u5f00'];
  setStatus(it.label + ' \u00b7 ' + (names[it.state] || '\u672a\u8fde\u63a5'), stateColor(it.state));
}
function renderTabs(){
  tabsEl.innerHTML = '';
  instances.forEach(function(it){
    var t = document.createElement('div');
    t.className = 'tab' + (it.id===activeId ? ' on' : '');
    var dot = document.createElement('span'); dot.className='dot'; dot.style.background = stateColor(it.state);
    var nm = document.createElement('span'); nm.textContent = it.label;
    var x = document.createElement('span'); x.className='x'; x.textContent='\u00d7'; x.title='\u5173\u95ed\u8fd9\u8def\u5206\u8eab';
    x.onclick = function(ev){ ev.stopPropagation(); closeInstance(it.id); };
    t.appendChild(dot); t.appendChild(nm); t.appendChild(x);
    t.onclick = function(){ switchInstance(it.id); };
    tabsEl.appendChild(t);
  });
}
function switchInstance(id){
  activeId = id;
  instances.forEach(function(it){ it.el.className = 'inst' + (it.id===id ? ' on' : ''); });
  renderTabs(); showActiveStatus();
  var it = active();
  if (it && it.client) vscodeApi.postMessage({type:'readClipboard'});
}
function newInstance(){
  var id = nextId++;
  var el = document.createElement('div'); el.className = 'inst';
  container.appendChild(el);
  var it = { id: id, label: '\u5206\u8eab' + id, el: el, client: null, display: null,
             connecting: false, userDisconnected: false, retries: 0, retryTimer: null, state: 0 };
  instances.push(it);
  switchInstance(id);
  return it;
}
function addInstance(){ var it = newInstance(); connectInstance(it); }
function closeInstance(id){
  var idx = instances.findIndex(function(x){ return x.id===id; });
  if (idx < 0) return;
  var it = instances[idx];
  it.userDisconnected = true;
  if (it.retryTimer) { clearTimeout(it.retryTimer); it.retryTimer = null; }
  if (it.client) { try { it.client.disconnect(); } catch(e) {} it.client = null; }
  try { container.removeChild(it.el); } catch(e) {}
  instances.splice(idx, 1);
  if (activeId === id) { activeId = instances.length ? instances[instances.length-1].id : null; }
  instances.forEach(function(x){ x.el.className = 'inst' + (x.id===activeId ? ' on' : ''); });
  renderTabs(); showActiveStatus();
}

async function connectInstance(it) {
  if (!it || it.connecting) return;
  it.connecting = true;
  it.userDisconnected = false;
  if (it.retryTimer) { clearTimeout(it.retryTimer); it.retryTimer = null; }
  if (it.client) { try { it.client.disconnect(); } catch(e) {} it.client = null; }
  setStatus(it.label + ' \u00b7 \u53d6 token...', '#ffcc00');
  const w = container.clientWidth;
  const h = container.clientHeight;
  let tokenData;
  try {
    // \u6bcf\u6b21\u94f8\u65b0 token = \u65b0\u5f00\u4e00\u8def\u72ec\u7acb RDP \u8fde\u63a5\uff08guest \u5173\u5355\u4f1a\u8bdd\u9650\u5236\u540e\u5373\u5404\u6210\u4e00\u8def\u72ec\u7acb\u4f1a\u8bdd\uff09
    const q = ACCOUNT ? ('account=' + encodeURIComponent(ACCOUNT)) : ('ide=' + IDE_SESSION);
    const r = await fetch(TUNNEL_HTTP + '/token?' + q + '&width=' + w + '&height=' + h);
    tokenData = await r.json();
    if (tokenData.error) { setStatus(it.label + ' \u00b7 \u4ee4\u724c: ' + tokenData.error, '#ff4444'); it.connecting = false; return; }
  } catch (e) { setStatus(it.label + ' \u00b7 \u4ee4\u724c\u83b7\u53d6\u5931\u8d25: ' + e.message, '#ff4444'); it.connecting = false; return; }
  let wsHost = '127.0.0.1', wsScheme = 'ws';
  try { const tu = new URL(TUNNEL_HTTP); wsHost = tu.hostname || wsHost; wsScheme = (tu.protocol === 'https:') ? 'wss' : 'ws'; } catch (e) {}
  const wsUrl = wsScheme + '://' + wsHost + ':' + TUNNEL_WS_PORT + '/?token=' + encodeURIComponent(tokenData.token);
  setStatus(it.label + ' \u00b7 \u5efa\u7acb WS \u96a7\u9053...', '#ffcc00');
  const tunnel = new Guacamole.WebSocketTunnel(wsUrl);
  const client = new Guacamole.Client(tunnel);
  it.client = client;
  const display = client.getDisplay();
  it.display = display;
  var ov = document.getElementById('overlay'); if (ov) ov.remove();
  it.el.innerHTML = '';
  it.el.appendChild(display.getElement());
  // \u9f20\u6807（\u6309\u663e\u793a\u7f29\u653e\u6362\u7b97\u56de\u771f\u5b9e\u5750\u6807）——\u53ea\u4f5c\u7528\u4e8e\u672c\u5206\u8eab\u81ea\u5df1\u7684\u753b\u5e03
  const mouse = new Guacamole.Mouse(display.getElement());
  mouse.onEach(['mousedown','mousemove','mouseup'], function(e) {
    if (!it.client) return;
    var s = display.getScale() || 1;
    var st = e.state;
    if (s !== 1) st = new Guacamole.Mouse.State(st.x / s, st.y / s, st.left, st.middle, st.right, st.up, st.down);
    it.client.sendMouseState(st, true);
  });
  // \u81ea\u9002\u5e94\u7f29\u653e
  display.onresize = function(dw, dh) {
    const scale = Math.min(container.clientWidth / dw, container.clientHeight / dh, 1);
    display.scale(scale);
  };
  // \u526a\u8d34\u677f\uff1a\u8fdc\u7aef\u2192\u672c\u5730\uff08\u4ec5\u6d3b\u52a8\u5206\u8eab\u56de\u5199\uff0c\u907f\u514d\u591a\u8def\u4e92\u8e29\uff09
  client.onclipboard = function(stream, mimetype) {
    // 注意：本段位于模板字面量内，\\/ 会被吞成 /，禁用含斜杠的正则字面量（真机踩坑：SyntaxError 令整段脚本报废）。
    if (mimetype.indexOf('text/') !== 0) { try { stream.sendAck('OK', 0); } catch(e) {} return; }
    var reader = new Guacamole.StringReader(stream);
    var data = '';
    reader.ontext = function(t) { data += t; };
    reader.onend = function() {
      if (it.id !== activeId) return;
      if (data && data !== lastLocalClip) { lastRemoteClip = data; vscodeApi.postMessage({type:'clipboard', text: data}); }
    };
  };
  client.onstatechange = function(state) {
    it.state = state;
    renderTabs();
    if (it.id === activeId) showActiveStatus();
    vscodeApi.postMessage({type:'state', state: state, instance: it.id});
    if (state === 3) { it.retries = 0; if (it.id === activeId) vscodeApi.postMessage({type:'readClipboard'}); }
    if (state === 5 && !it.userDisconnected) {
      if (it.retries < MAX_RETRIES) {
        var delay = Math.min(2000 * Math.pow(2, it.retries), 15000);
        it.retries++;
        if (it.id === activeId) setStatus(it.label + ' \u00b7 \u65ad\u7ebf\uff0c' + (delay/1000) + 's \u540e\u91cd\u8fde(' + it.retries + '/' + MAX_RETRIES + ')...', '#ff8800');
        if (it.retryTimer) clearTimeout(it.retryTimer);
        it.retryTimer = setTimeout(function(){ connectInstance(it); }, delay);
      } else if (it.id === activeId) {
        setStatus(it.label + ' \u00b7 \u5df2\u65ad\u5f00\uff08\u91cd\u8fde\u6b21\u6570\u8017\u5c3d\uff0c\u70b9\u300c\u8fde\u63a5\u300d\u624b\u52a8\u91cd\u8bd5\uff09', '#ff4444');
      }
    }
  };
  client.onerror = function(s) { if (it.id === activeId) setStatus(it.label + ' \u00b7 \u9519\u8bef: ' + (s.message || s.code || ''), '#ff4444'); };
  tunnel.onerror = function(s) { if (it.id === activeId) setStatus(it.label + ' \u00b7 \u96a7\u9053\u9519\u8bef: ' + (s && (s.message || s.code) || ''), '#ff4444'); };
  client.connect();
  it.connecting = false;
}

function doConnect(){ var it = active() || newInstance(); connectInstance(it); }
function doDisconnect(){
  var it = active(); if (!it) return;
  it.userDisconnected = true;
  if (it.retryTimer) { clearTimeout(it.retryTimer); it.retryTimer = null; }
  if (it.client) { try { it.client.disconnect(); } catch(e) {} it.client = null; }
}

// \u952e\u76d8\uff1a\u5168\u5c40\u4e00\u4efd\uff0c\u53ea\u8def\u7531\u5230\u6d3b\u52a8\u5206\u8eab\uff08\u591a\u8def\u5e76\u884c\u4e92\u4e0d\u4e32\u952e\uff09
const keyboard = new Guacamole.Keyboard(document);
keyboard.onkeydown = function(k) { var it = active(); if (it && it.client) it.client.sendKeyEvent(1, k); };
keyboard.onkeyup = function(k) { var it = active(); if (it && it.client) it.client.sendKeyEvent(0, k); };

// \u526a\u8d34\u677f\uff1a\u672c\u5730\u2192\u8fdc\u7aef\uff08\u53ea\u53d1\u7ed9\u6d3b\u52a8\u5206\u8eab\uff09
function sendClipboard(text) {
  var it = active();
  if (!it || !it.client || typeof text !== 'string' || !text || text === lastRemoteClip) return;
  lastLocalClip = text;
  try {
    var stream = it.client.createClipboardStream('text/plain');
    var writer = new Guacamole.StringWriter(stream);
    writer.sendText(text);
    writer.sendEnd();
  } catch (e) {}
}
window.addEventListener('message', function(ev) {
  var msg = ev.data || {};
  if (msg.type === 'clipboardData') sendClipboard(msg.text);
  if (msg.type === 'addInstance') addInstance();
});
window.addEventListener('focus', function() { var it = active(); if (it && it.client) vscodeApi.postMessage({type:'readClipboard'}); });

function doFullscreen() { vscodeApi.postMessage({type:'fullscreen'}); }

// \u6fc0\u6d3b\u5373\u81ea\u52a8\u8fde\u7b2c\u4e00\u8def\u5206\u8eab
setTimeout(doConnect, 300);
</script></body></html>`;
}

// account 为空=本 IDE 窗口默认会话（ide_<hash>）；非空=指定 Windows 账号一路独立桌面。
async function openDesktop(context, account) {
  const sessionId = windowSessionId();
  const c = cfg();
  const key = account || sessionId;
  const existing = desktopPanels.get(key);
  if (existing) { existing.reveal(); return; }
  const accounts = await fetchAccounts(c.tunnelHttpUrl);
  const title = account ? ("DAO \u684c\u9762 \u00b7 " + account) : ("DAO \u684c\u9762 \u00b7 " + sessionId);
  const p = vscode.window.createWebviewPanel(
    "daoWinDesktop", title, vscode.ViewColumn.Active,
    { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "media")] }
  );
  desktopPanels.set(key, p);
  p.webview.html = desktopHtml(p.webview, context, sessionId, account || null, c.tunnelHttpUrl, c.tunnelWsPort, accounts);
  p.onDidDispose(() => { desktopPanels.delete(key); });
  p.webview.onDidReceiveMessage((msg) => {
    if (msg.type === "state" && msg.state === 3) {
      setStatus((account || sessionId) + " \u25cf", "\u684c\u9762\u5df2\u8fde " + c.tunnelHttpUrl);
    }
    if (msg.type === "fullscreen") {
      vscode.commands.executeCommand("workbench.action.toggleEditorWidths");
    }
    if (msg.type === "openAccount" && msg.account) {
      openDesktop(context, msg.account);
    }
    if (msg.type === "clipboard" && typeof msg.text === "string") {
      vscode.env.clipboard.writeText(msg.text);
    }
    if (msg.type === "readClipboard") {
      vscode.env.clipboard.readText().then((text) => {
        try { p.webview.postMessage({ type: "clipboardData", text }); } catch (e) {}
      });
    }
  });
}

// 选账号开桌面（QuickPick 列出隧道已知账号 + 手填）
async function openAccountDesktop(context) {
  const c = cfg();
  const accounts = await fetchAccounts(c.tunnelHttpUrl);
  const items = accounts.map((a) => ({ label: a.name, description: a.hostname + ":" + a.port }));
  items.push({ label: "$(add) \u5176\u4ed6\u8d26\u53f7\u2026", description: "\u624b\u52a8\u8f93\u5165\u8d26\u53f7\u540d" });
  const pick = await vscode.window.showQuickPick(items, { placeHolder: "\u9009\u62e9\u8981\u6253\u5f00\u684c\u9762\u7684 Windows \u8d26\u53f7" });
  if (!pick) return;
  let account = pick.label;
  if (pick.label.indexOf("\u5176\u4ed6\u8d26\u53f7") >= 0) {
    account = await vscode.window.showInputBox({ prompt: "\u8d26\u53f7\u540d", validateInput: (v) => /^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$/.test(v || "") ? null : "\u9650\u5b57\u6bcd\u6570\u5b57\u4e0e . _ -\uff0c\u2264 20" });
    if (!account) return;
  }
  openDesktop(context, account);
}

// 账号管理（在插件内建号/销号，复用桥 /api/account.*）
async function manageAccount(context, op) {
  const info = await ensureBridge(context);
  if (!info) { vscode.window.showErrorMessage("DAO: \u673a\u63a7\u6865\u4e0d\u53ef\u8fbe\uff0c\u65e0\u6cd5\u7ba1\u7406\u8d26\u53f7"); return; }
  const { url, token } = info;
  if (op === "list") {
    const r = await apiCall(url, token, "GET", "/api/account.list");
    const names = ((r.body && r.body.accounts) || []).map((a) => a.name + (a.session ? " \u25cf" + a.session.state : ""));
    vscode.window.showInformationMessage("DAO \u8d26\u53f7: " + (names.join(", ") || "\uff08\u65e0\uff09"));
    return;
  }
  if (op === "create") {
    const name = await vscode.window.showInputBox({ prompt: "\u65b0\u5efa Windows \u8d26\u53f7\u540d", validateInput: (v) => /^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$/.test(v || "") ? null : "\u9650\u5b57\u6bcd\u6570\u5b57\u4e0e . _ -\uff0c\u2264 20" });
    if (!name) return;
    const r = await apiCall(url, token, "POST", "/api/account.create", { name }, 60000);
    if (r.body && r.body.ok) { vscode.window.showInformationMessage("DAO \u8d26\u53f7\u5df2\u5efa: " + name + "\uff0c\u53ef\u5728\u300c\u9009\u8d26\u53f7\u5f00\u684c\u9762\u300d\u4e2d\u6253\u5f00"); openDesktop(context, name); }
    else vscode.window.showErrorMessage("DAO \u5efa\u53f7\u5931\u8d25: " + ((r.body && r.body.error) || r.status));
    return;
  }
  if (op === "destroy") {
    const r0 = await apiCall(url, token, "GET", "/api/account.list");
    const names = ((r0.body && r0.body.accounts) || []).map((a) => a.name);
    const name = await vscode.window.showQuickPick(names, { placeHolder: "\u9009\u62e9\u8981\u9500\u6bc1\u7684\u8d26\u53f7" });
    if (!name) return;
    const r = await apiCall(url, token, "POST", "/api/account.destroy", { name }, 60000);
    vscode.window.showInformationMessage(r.body && r.body.ok ? ("DAO \u8d26\u53f7\u5df2\u9500\u6bc1: " + name) : ("DAO \u9500\u53f7\u5931\u8d25: " + ((r.body && r.body.error) || r.status)));
  }
}

// —— 控制面板（旧版按钮面板，降级为辅助自动化后端）——
function panelHtml(sessionId) {
  return `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<style>
 body{font-family:var(--vscode-font-family);padding:12px;color:var(--vscode-foreground);}
 h2{margin:4px 0;} .sid{opacity:.7;font-size:12px;}
 fieldset{border:1px solid var(--vscode-panel-border);border-radius:6px;margin:10px 0;padding:8px 10px;}
 legend{font-weight:600;} button{margin:3px 4px 3px 0;padding:4px 10px;cursor:pointer;
   background:var(--vscode-button-background);color:var(--vscode-button-foreground);border:none;border-radius:4px;}
 button:hover{background:var(--vscode-button-hoverBackground);}
 input{background:var(--vscode-input-background);color:var(--vscode-input-foreground);
   border:1px solid var(--vscode-input-border);border-radius:4px;padding:3px 6px;margin:2px;}
 pre{background:var(--vscode-textCodeBlock-background);padding:8px;border-radius:6px;max-height:340px;overflow:auto;white-space:pre-wrap;}
 .row{display:flex;flex-wrap:wrap;align-items:center;}
</style></head><body>
<h2>☯ DAO Windows Agent</h2>
<div class="sid">本 IDE 窗口 = 隔离会话 <b>${sessionId}</b> · 与用户真实桌面并行、互不干扰（类多RDP效果，单账号零配置）</div>

<fieldset><legend>桥 / 会话</legend>
 <button onclick="call('health')">健康检查</button>
 <button onclick="call('apps')">已装应用</button>
 <button onclick="call('session.create')">创建本窗口会话</button>
 <button onclick="call('session.list')">会话列表</button>
</fieldset>

<fieldset><legend>级别① 整机底座（system profile · 无头）</legend>
 <div class="row"><input id="cmd" placeholder="shell 命令，如 hostname" style="width:60%">
 <button onclick="sysExec()">exec</button></div>
 <button onclick="sysInvoke('sysinfo')">sysinfo</button>
 <button onclick="sysInvoke('processes')">进程列表</button>
</fieldset>

<fieldset><legend>级别② 隔离桌面标靶（notepad · 类虚拟机）</legend>
 <button onclick="openApp('notepad')">在隔离桌面开记事本</button>
 <div class="row"><input id="txt" value="道法自然 DAO IDE 隔离会话 OK" style="width:60%">
 <button onclick="npType()">写入文本</button>
 <button onclick="npInvoke('read_text')">读回文本</button></div>
 <button onclick="npInvoke('screenshot')">隔离桌面截图(级别③取证)</button>
 <button onclick="npInvoke('controls_tree')">控件树</button>
</fieldset>

<fieldset><legend>动词检索</legend>
 <div class="row"><input id="q" placeholder="中文/英文查询，如 记事本 写入" style="width:60%">
 <button onclick="searchVerbs()">search_verbs</button></div>
</fieldset>

<h3>结果</h3><pre id="out">（点击上方按钮）</pre>
<script>
 const vscode = acquireVsCodeApi();
 const SID = ${JSON.stringify(sessionId)};
 function post(m){ vscode.postMessage(m); }
 function call(action){ post({action}); }
 function openApp(app){ post({action:'session.open_app', app_id:app}); }
 function npType(){ post({action:'session.invoke', app_id:'notepad', verb:'type_text', params:{text:document.getElementById('txt').value}}); }
 function npInvoke(verb){ post({action:'session.invoke', app_id:'notepad', verb}); }
 function sysExec(){ post({action:'session.invoke', app_id:'system', verb:'exec', params:{cmd:document.getElementById('cmd').value}}); }
 function sysInvoke(verb){ post({action:'session.invoke', app_id:'system', verb}); }
 function searchVerbs(){ post({action:'search_verbs', query:document.getElementById('q').value}); }
 window.addEventListener('message', e=>{ document.getElementById('out').textContent = e.data.text; });
</script></body></html>`;
}

async function handlePanelMessage(context, msg) {
  const sessionId = windowSessionId();
  const info = await ensureBridge(context);
  if (!info) {
    panel.webview.postMessage({ text: "✗ 机控桥不可达（检查 daoWin.bridgeUrl / autostart / pythonPath）。详见输出面板 DAO Windows Agent。" });
    return;
  }
  const { url, token } = info;
  try {
    let r;
    if (msg.action === "health") r = await apiCall(url, token, "GET", "/api/health");
    else if (msg.action === "apps") r = await apiCall(url, token, "GET", "/api/apps");
    else if (msg.action === "session.list") r = await apiCall(url, token, "GET", "/api/session.list");
    else if (msg.action === "session.create") r = await apiCall(url, token, "POST", "/api/session.create", { session_id: sessionId });
    else if (msg.action === "search_verbs") r = await apiCall(url, token, "POST", "/api/search_verbs", { query: msg.query || "" });
    else if (msg.action === "session.open_app") {
      await apiCall(url, token, "POST", "/api/session.create", { session_id: sessionId });
      r = await apiCall(url, token, "POST", "/api/session.open_app", { session_id: sessionId, app_id: msg.app_id });
      // 注册后立即执行 open 动词，真正把窗口起到隔离桌面（system 等无 open 动词的忽略失败）
      if (r.body && r.body.ok !== false) {
        const ro = await apiCall(url, token, "POST", "/api/session.invoke", { session_id: sessionId, app_id: msg.app_id, verb: "open", params: {} }, 30000);
        if (ro.body && ro.body.ok !== false) r = ro;
      }
    }
    else if (msg.action === "session.invoke") {
      r = await apiCall(url, token, "POST", "/api/session.invoke", { session_id: sessionId, app_id: msg.app_id, verb: msg.verb, params: msg.params || {} }, 30000);
      // 应用未注册到会话则自动 open_app 后重试一次（免用户手工两步）
      if (r.body && r.body.ok === false && /open_app/.test(String(r.body.error || ""))) {
        await apiCall(url, token, "POST", "/api/session.create", { session_id: sessionId });
        await apiCall(url, token, "POST", "/api/session.open_app", { session_id: sessionId, app_id: msg.app_id });
        r = await apiCall(url, token, "POST", "/api/session.invoke", { session_id: sessionId, app_id: msg.app_id, verb: msg.verb, params: msg.params || {} }, 30000);
      }
    }
    else r = { status: 400, body: { error: "未知动作 " + msg.action } };
    const tag = r.status === 200 ? "✓" : "✗ HTTP " + r.status;
    panel.webview.postMessage({ text: tag + " " + msg.action + " @ " + url + "\n" + JSON.stringify(r.body, null, 2) });
  } catch (e) {
    panel.webview.postMessage({ text: "✗ " + msg.action + " 异常: " + e.message });
  }
}

function openPanel(context) {
  const sessionId = windowSessionId();
  if (panel) { panel.reveal(); return; }
  panel = vscode.window.createWebviewPanel("daoWinPanel", "DAO \u63a7\u5236\u9762", vscode.ViewColumn.Beside, { enableScripts: true, retainContextWhenHidden: true });
  panel.webview.html = panelHtml(sessionId);
  panel.onDidDispose(() => { panel = null; });
  panel.webview.onDidReceiveMessage((msg) => handlePanelMessage(context, msg));
}

// —— AI 交互基底面板（@ 调度）：一句自然语言 → 裁定通用层/领域工作层 → 一键执行候选动词 ——
let askPanel = null;

function askHtml(sessionId) {
  return `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><style>
 body{font-family:var(--vscode-font-family);padding:12px;color:var(--vscode-foreground);}
 h2{margin:2px 0;} .sid{opacity:.7;font-size:12px;margin-bottom:8px;}
 .bar{display:flex;gap:6px;} textarea{flex:1;min-height:52px;background:var(--vscode-input-background);
   color:var(--vscode-input-foreground);border:1px solid var(--vscode-input-border);border-radius:6px;padding:6px;font-family:inherit;}
 button{padding:5px 12px;cursor:pointer;background:var(--vscode-button-background);color:var(--vscode-button-foreground);border:none;border-radius:5px;}
 button:hover{background:var(--vscode-button-hoverBackground);}
 .layer{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;margin-left:6px;}
 .universal{background:#264f78;} .domain{background:#4b3a66;}
 .hint{border:1px solid var(--vscode-panel-border);border-radius:6px;padding:6px 8px;margin:6px 0;cursor:pointer;}
 .hint:hover{border-color:var(--vscode-focusBorder);} .hint code{opacity:.85;}
 .un{color:#e0a030;} pre{background:var(--vscode-textCodeBlock-background);padding:8px;border-radius:6px;white-space:pre-wrap;max-height:260px;overflow:auto;}
</style></head><body>
<h2>☯ DAO · AI 交互基底</h2>
<div class="sid">本窗口会话 <b>${sessionId}</b> · 无 @ → 整机通用层；<code>@句柄</code> 唤起领域工作层（如 @kicad @freecad @paint）</div>
<div class="bar"><textarea id="goal" placeholder="说出目标，例如：打开记事本写入'道法自然' 或 @kicad 导出 gerber"></textarea>
 <button onclick="route()">调度</button></div>
<div id="decision"></div>
<h3>结果</h3><pre id="out">（输入目标后点「调度」——先定层与候选动词，再点候选执行）</pre>
<script>
 const vscode = acquireVsCodeApi();
 function route(){ vscode.postMessage({kind:'route', text: document.getElementById('goal').value}); }
 function run(app, verb){ vscode.postMessage({kind:'invoke', app_id:app, verb:verb}); }
 window.addEventListener('message', e=>{
   const m = e.data;
   if (m.kind === 'decision'){
     const d = m.data; let h = '';
     h += '<div>落点<span class="layer '+d.layer+'">'+(d.layer==='universal'?'整机通用层':'领域工作层')+'</span> 目标: <b>'+(d.targets.join(', ')||'—')+'</b></div>';
     if (d.unresolved && d.unresolved.length) h += '<div class="un">未就绪句柄（子插件未安装）: @'+d.unresolved.join(' @')+'</div>';
     if (d.blocked_by_mode && d.blocked_by_mode.length) h += '<div class="un">模式 '+(d.mode||'')+' 未开放: '+d.blocked_by_mode.join(', ')+'（先切换模式）</div>';
     (d.verb_hints||[]).forEach(v=>{ h += '<div class="hint" onclick="run(\\''+v.app_id+'\\',\\''+v.verb+'\\')">▶ <b>'+v.verb+'</b> <code>@'+v.app_id+'</code> — '+(v.summary||v.description||'')+'</div>'; });
     if (!(d.verb_hints||[]).length) h += '<div class="hint">（无候选动词，可直接在控制面手动执行）</div>';
     document.getElementById('decision').innerHTML = h;
   } else if (m.kind === 'result'){ document.getElementById('out').textContent = m.text; }
 });
</script></body></html>`;
}

async function handleAskMessage(context, msg) {
  const sessionId = windowSessionId();
  const info = await ensureBridge(context);
  if (!info) { askPanel.webview.postMessage({ kind: "result", text: "\u2717 \u673a\u63a7\u6865\u4e0d\u53ef\u8fbe" }); return; }
  const { url, token } = info;
  try {
    if (msg.kind === "route") {
      const r = await apiCall(url, token, "POST", "/api/route", { text: msg.text || "" });
      if (r.status === 200 && r.body) askPanel.webview.postMessage({ kind: "decision", data: r.body });
      askPanel.webview.postMessage({ kind: "result", text: "route @ " + url + "\n" + JSON.stringify(r.body, null, 2) });
    } else if (msg.kind === "invoke") {
      await apiCall(url, token, "POST", "/api/session.create", { session_id: sessionId });
      await apiCall(url, token, "POST", "/api/session.open_app", { session_id: sessionId, app_id: msg.app_id });
      const r = await apiCall(url, token, "POST", "/api/session.invoke", { session_id: sessionId, app_id: msg.app_id, verb: msg.verb, params: {} }, 30000);
      const tag = r.status === 200 ? "\u2713" : "\u2717 HTTP " + r.status;
      askPanel.webview.postMessage({ kind: "result", text: tag + " " + msg.app_id + "." + msg.verb + "\n" + JSON.stringify(r.body, null, 2) });
    }
  } catch (e) {
    askPanel.webview.postMessage({ kind: "result", text: "\u2717 " + msg.kind + " \u5f02\u5e38: " + e.message });
  }
}

function openAsk(context) {
  const sessionId = windowSessionId();
  if (askPanel) { askPanel.reveal(); return; }
  askPanel = vscode.window.createWebviewPanel("daoWinAsk", "DAO \u00b7 AI \u4ea4\u4e92", vscode.ViewColumn.Beside, { enableScripts: true, retainContextWhenHidden: true });
  askPanel.webview.html = askHtml(sessionId);
  askPanel.onDidDispose(() => { askPanel = null; });
  askPanel.webview.onDidReceiveMessage((msg) => handleAskMessage(context, msg));
}

// —— 归一主页 · Windows 总控（吸收 dao-vsix 六大板块「分而治之·网页套网页」范式）——
// 主页 = 统领全局：RDP 连接管理（官方 mstsc 五页配置收编）+ Windows 账号 + 子板块管理。
let homePanel = null;

function daoDir() { return path.join(require("os").homedir(), ".dao"); }
function rdpDir() { return path.join(daoDir(), "rdp"); }

// 子板块目录（可安装可移除·类 VS Code 插件体系）
const SUBPLUGIN_CATALOG = [
  { id: "freecad", name: "FreeCAD · 3D 建模", mention: "freecad", desc: "AI 纵深操作 FreeCAD 参数化建模", repo: "Dao-3D-Modeling-Agent" },
  { id: "kicad", name: "KiCad · PCB 设计", mention: "kicad", desc: "原理图/布线/制造文件全流程", repo: "Dao-PCB-Design-Agent" },
  { id: "jlceda", name: "嘉立创EDA · PCB 设计", mention: "jlceda", desc: "嘉立创EDA 专业版驱动", repo: "Dao-PCB-Design-Agent" },
  { id: "homeassistant", name: "Home Assistant · 智能家居", mention: "ha", desc: "状态/服务调用/自动化管理", repo: "ha-copilot" },
];

function rdpSafeName(name) {
  const s = String(name || "").trim().replace(/[^\w\u4e00-\u9fa5.-]/g, "_").slice(0, 60);
  return s || null;
}

// 官方远程桌面连接（mstsc）五页配置 → 标准 .rdp 文件（常规/显示/本地资源/体验/高级）
function rdpFileContent(p) {
  const b = (v, d) => (v === undefined || v === null ? d : (v ? 1 : 0));
  const lines = [
    "full address:s:" + (p.host || "") + (p.port && String(p.port) !== "3389" ? ":" + p.port : ""),
    "username:s:" + (p.username || ""),
    "screen mode id:i:" + (p.fullscreen === false ? 1 : 2),
    "desktopwidth:i:" + (parseInt(p.width, 10) || 1920),
    "desktopheight:i:" + (parseInt(p.height, 10) || 1080),
    "session bpp:i:" + (parseInt(p.bpp, 10) || 32),
    "use multimon:i:" + b(p.multimon, 0),
    "audiomode:i:" + (parseInt(p.audiomode, 10) || 0),
    "redirectclipboard:i:" + b(p.clipboard, 1),
    "redirectprinters:i:" + b(p.printers, 0),
    "drivestoredirect:s:" + (p.drives ? "*" : ""),
    "connection type:i:" + (parseInt(p.conntype, 10) || 7),
    "networkautodetect:i:" + b(p.autodetect, 1),
    "compression:i:1",
    "autoreconnection enabled:i:" + b(p.autoreconnect, 1),
    "authentication level:i:" + (parseInt(p.authlevel, 10) || 2),
    "prompt for credentials:i:" + b(p.promptcred, 0),
    "gatewayhostname:s:" + (p.gateway || ""),
    "gatewayusagemethod:i:" + (p.gateway ? 1 : 4),
    "remoteapplicationmode:i:0",
    "smart sizing:i:1",
  ];
  return lines.join("\r\n") + "\r\n";
}

function listRdpProfiles() {
  const out = [];
  try {
    for (const f of fs.readdirSync(rdpDir())) {
      if (!f.endsWith(".json")) continue;
      try { out.push(Object.assign({ name: f.slice(0, -5) }, JSON.parse(fs.readFileSync(path.join(rdpDir(), f), "utf-8")))); } catch (_) {}
    }
  } catch (_) {}
  return out;
}

function listSubplugins() {
  const dir = subpluginDir();
  const installed = new Map();
  try {
    for (const f of fs.readdirSync(dir)) {
      const off = f.endsWith(".json.off");
      if (!f.endsWith(".json") && !off) continue;
      try {
        const d = JSON.parse(fs.readFileSync(path.join(dir, f), "utf-8"));
        if (d.app_id) installed.set(d.app_id, Object.assign({ enabled: !off }, d));
      } catch (_) {}
    }
  } catch (_) {}
  const rows = [];
  for (const c of SUBPLUGIN_CATALOG) {
    const inst = installed.get(c.id);
    rows.push(Object.assign({}, c, { installed: !!inst, enabled: inst ? inst.enabled !== false : false, verbs: inst && Array.isArray(inst.verbs) ? inst.verbs.length : 0 }));
    installed.delete(c.id);
  }
  for (const [id, inst] of installed) {
    rows.push({ id, name: inst.name || id, mention: inst.mention || id, desc: inst.summary || "", repo: "", installed: true, enabled: inst.enabled !== false, verbs: Array.isArray(inst.verbs) ? inst.verbs.length : 0 });
  }
  return rows;
}

async function homeInfoPayload(context) {
  const os = require("os");
  let accounts = [];
  const info = await ensureBridge(context).catch(() => null);
  if (info) {
    try { const r = await apiCall(info.url, info.token, "GET", "/api/account.list"); accounts = (r.body && r.body.accounts) || []; } catch (_) {}
  }
  if (!accounts.length) { try { accounts = await fetchAccounts(cfg().tunnelHttpUrl); } catch (_) {} }
  return {
    platform: process.platform, host: os.hostname(), user: os.userInfo().username,
    os: os.type() + " " + os.release(), bridge: info ? info.url : null,
    accounts, rdp: listRdpProfiles(), subplugins: listSubplugins(),
  };
}

async function handleHomeMessage(context, msg) {
  const reply = (data) => { try { homePanel.webview.postMessage(Object.assign({ kind: "homeData" }, { data })); } catch (_) {} };
  const refresh = async () => reply(await homeInfoPayload(context));
  try {
    if (msg.cmd === "homeInfo") return await refresh();
    if (msg.cmd === "rdpSave") {
      const nm = rdpSafeName(msg.profile && msg.profile.name);
      if (!nm) return reply({ error: "连接名不合法" });
      fs.mkdirSync(rdpDir(), { recursive: true });
      const p = Object.assign({}, msg.profile, { name: nm });
      fs.writeFileSync(path.join(rdpDir(), nm + ".json"), JSON.stringify(p, null, 2), "utf-8");
      fs.writeFileSync(path.join(rdpDir(), nm + ".rdp"), rdpFileContent(p), "utf-8");
      log("RDP 连接已存: " + nm);
      return await refresh();
    }
    if (msg.cmd === "rdpDelete") {
      const nm = rdpSafeName(msg.name);
      if (nm) for (const ext of [".json", ".rdp"]) { try { fs.unlinkSync(path.join(rdpDir(), nm + ext)); } catch (_) {} }
      return await refresh();
    }
    if (msg.cmd === "rdpLaunch") {
      const nm = rdpSafeName(msg.name);
      const rdpFile = nm && path.join(rdpDir(), nm + ".rdp");
      if (!rdpFile || !fs.existsSync(rdpFile)) return reply({ error: "连接不存在: " + msg.name });
      if (process.platform === "win32") {
        cp.spawn("mstsc.exe", [rdpFile], { detached: true, stdio: "ignore", windowsHide: false }).unref();
        vscode.window.showInformationMessage("DAO: 已启动远程桌面连接 " + nm);
      } else {
        try {
          const prof = JSON.parse(fs.readFileSync(path.join(rdpDir(), nm + ".json"), "utf-8"));
          cp.spawn("xfreerdp", ["/v:" + prof.host + (prof.port ? ":" + prof.port : ""), "/u:" + (prof.username || ""), "/cert:ignore"], { detached: true, stdio: "ignore" }).unref();
          vscode.window.showInformationMessage("DAO: 已尝试 xfreerdp 连接 " + nm);
        } catch (e) { vscode.window.showWarningMessage("DAO: 本平台无 mstsc，且 xfreerdp 启动失败: " + e.message); }
      }
      return;
    }
    if (msg.cmd === "subToggle") {
      const dir = subpluginDir();
      const on = path.join(dir, msg.id + ".json"), off = path.join(dir, msg.id + ".json.off");
      if (fs.existsSync(on)) fs.renameSync(on, off);
      else if (fs.existsSync(off)) fs.renameSync(off, on);
      return await refresh();
    }
    if (msg.cmd === "revealDir") {
      const dir = msg.which === "rdp" ? rdpDir() : subpluginDir();
      fs.mkdirSync(dir, { recursive: true });
      vscode.env.openExternal(vscode.Uri.file(dir));
      return;
    }
    if (msg.cmd === "openAccountDesktop") return openDesktop(context, msg.account);
    if (msg.cmd === "accountCreate") return manageAccount(context, "create");
    if (msg.cmd === "accountDestroy") return manageAccount(context, "destroy");
    if (msg.cmd === "switchMode") return switchMode(context);
  } catch (e) { reply({ error: e.message }); }
}

function homeHtml() {
  return `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><style>
 :root{--muted:var(--vscode-descriptionForeground)}
 body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);padding:0;margin:0;display:flex;height:100vh;overflow:hidden}
 .sb{width:46px;background:var(--vscode-sideBar-background);border-right:1px solid var(--vscode-panel-border);display:flex;flex-direction:column;align-items:center;padding-top:8px;gap:4px;flex-shrink:0}
 .ni{width:34px;height:34px;display:flex;align-items:center;justify-content:center;border-radius:7px;cursor:pointer;font-size:17px;opacity:.65}
 .ni:hover{background:var(--vscode-list-hoverBackground);opacity:1}
 .ni.on{background:var(--vscode-list-activeSelectionBackground);opacity:1}
 .main{flex:1;overflow:auto;padding:14px 16px}
 h2{margin:2px 0 10px} h3{margin:14px 0 6px}
 .card{border:1px solid var(--vscode-panel-border);border-radius:8px;padding:8px 12px;margin:6px 0;display:flex;align-items:center;gap:10px}
 .card .grow{flex:1;min-width:0} .sub{font-size:12px;color:var(--muted)}
 button{padding:4px 10px;cursor:pointer;background:var(--vscode-button-background);color:var(--vscode-button-foreground);border:none;border-radius:5px;font-size:12px}
 button.ghost{background:transparent;border:1px solid var(--vscode-panel-border);color:var(--vscode-foreground)}
 input,select{background:var(--vscode-input-background);color:var(--vscode-input-foreground);border:1px solid var(--vscode-input-border);border-radius:4px;padding:3px 6px;margin:2px;font-size:12px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:4px}
 .empty{opacity:.6;font-size:13px;padding:8px 2px}
 .badge{font-size:11px;padding:1px 7px;border-radius:9px;background:var(--vscode-badge-background);color:var(--vscode-badge-foreground)}
 fieldset{border:1px solid var(--vscode-panel-border);border-radius:8px;margin:8px 0;padding:8px 10px} legend{font-size:12px;font-weight:600}
 .hide{display:none}
</style></head><body>
<div class="sb">
 <div class="ni on" data-v="win" onclick="sw('win')" title="Windows 总控 · RDP/账号/子板块">🪟</div>
 <div class="ni" data-v="mode" onclick="post({cmd:'switchMode'})" title="模式切换">⚙️</div>
</div>
<div class="main" id="main"><div class="empty">正在读取 Windows 总控数据…</div></div>
<script>
const vscodeApi = acquireVsCodeApi();
let S = null, editing = null;
function post(m){ vscodeApi.postMessage(m); }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
function sw(v){ /* 单板块阶段一：仅 win */ render(); }
function render(){
  var m = document.getElementById('main');
  if (!S) { m.innerHTML = '<div class="empty">正在读取…</div>'; return; }
  var h = '<h2>🪟 Windows 总控</h2><div class="sub">' + esc(S.host) + ' · ' + esc(S.user) + ' · ' + esc(S.os) + (S.bridge ? ' · 桥 ' + esc(S.bridge) : ' · 桥未连') + '</div>';
  h += '<h3>远程桌面连接 <button class="ghost" onclick="editRdp(null)">＋新建</button> <button class="ghost" onclick="post({cmd:\\'revealDir\\',which:\\'rdp\\'})">打开目录</button></h3>';
  if (!(S.rdp||[]).length) h += '<div class="empty">尚无连接配置——「＋新建」收编官方 mstsc 五页配置（常规/显示/本地资源/体验/高级）</div>';
  (S.rdp||[]).forEach(function(p){
    h += '<div class="card"><div class="grow"><b>' + esc(p.name) + '</b><div class="sub">' + esc(p.host||'') + (p.port?':'+esc(p.port):'') + (p.username?' · '+esc(p.username):'') + '</div></div>'
      + '<button onclick="post({cmd:\\'rdpLaunch\\',name:\\''+esc(p.name)+'\\'})">连接</button>'
      + '<button class="ghost" onclick="editRdp(\\''+esc(p.name)+'\\')">编辑</button>'
      + '<button class="ghost" onclick="post({cmd:\\'rdpDelete\\',name:\\''+esc(p.name)+'\\'})">删除</button></div>';
  });
  h += '<div id="rdpForm" class="hide"></div>';
  h += '<h3>本机 Windows 账号 <button class="ghost" onclick="post({cmd:\\'accountCreate\\'})">＋建号</button> <button class="ghost" onclick="post({cmd:\\'accountDestroy\\'})">销号</button></h3>';
  if (!(S.accounts||[]).length) h += '<div class="empty">' + (S.platform === 'win32' ? '暂无账号数据（桥/隧道未连）' : '非 Windows 平台——账号盘点在真机/冷启动 VM 生效') + '</div>';
  (S.accounts||[]).forEach(function(a){
    var nm = a.name || a;
    h += '<div class="card"><div class="grow"><b>' + esc(nm) + '</b><div class="sub">' + esc(a.hostname? a.hostname+':'+a.port : (a.session? '会话 '+a.session.state : '')) + '</div></div>'
      + '<button onclick="post({cmd:\\'openAccountDesktop\\',account:\\''+esc(nm)+'\\'})">开桌面</button></div>';
  });
  h += '<h3>子板块 · 可安装可移除（类 VS Code 插件） <button class="ghost" onclick="post({cmd:\\'revealDir\\',which:\\'sub\\'})">打开目录</button></h3>';
  (S.subplugins||[]).forEach(function(s){
    h += '<div class="card"><div class="grow"><b>' + esc(s.name) + '</b> <span class="badge">@' + esc(s.mention) + '</span>'
      + (s.installed ? ' <span class="badge">' + (s.enabled?'已启用':'已停用') + (s.verbs?' · '+s.verbs+' 动词':'') + '</span>' : '')
      + '<div class="sub">' + esc(s.desc) + (s.repo? ' · '+esc(s.repo):'') + '</div></div>'
      + (s.installed ? '<button class="ghost" onclick="post({cmd:\\'subToggle\\',id:\\''+esc(s.id)+'\\'})">' + (s.enabled?'停用':'启用') + '</button>'
                     : '<span class="sub">未安装（装同名子插件或落描述符即收编）</span>')
      + '</div>';
  });
  m.innerHTML = h;
  if (editing !== null) showRdpForm(editing);
}
function editRdp(name){ editing = name || ''; render(); }
function showRdpForm(name){
  var p = {}; (S.rdp||[]).forEach(function(x){ if (x.name === name) p = x; });
  var f = document.getElementById('rdpForm'); f.className = '';
  function iv(k,d){ return esc(p[k] !== undefined ? p[k] : (d===undefined?'':d)); }
  function ck(k,d){ return (p[k] !== undefined ? p[k] : d) ? ' checked' : ''; }
  f.innerHTML = '<fieldset><legend>' + (name?'编辑':'新建') + ' RDP 连接（官方五页配置收编）</legend>'
   + '<div>常规：<input id="f_name" placeholder="连接名" value="' + iv('name') + '"' + (name?' disabled':'') + '> <input id="f_host" placeholder="主机/IP" value="' + iv('host') + '"> <input id="f_port" placeholder="端口 3389" size="6" value="' + iv('port') + '"> <input id="f_user" placeholder="用户名" value="' + iv('username') + '"></div>'
   + '<div>显示：<input id="f_w" size="5" placeholder="宽 1920" value="' + iv('width') + '"> × <input id="f_h" size="5" placeholder="高 1080" value="' + iv('height') + '"> <label><input type="checkbox" id="f_full"' + ck('fullscreen',true) + '>全屏</label> <label><input type="checkbox" id="f_multi"' + ck('multimon',false) + '>多显示器</label></div>'
   + '<div>本地资源：<label><input type="checkbox" id="f_clip"' + ck('clipboard',true) + '>剪贴板</label> <label><input type="checkbox" id="f_prn"' + ck('printers',false) + '>打印机</label> <label><input type="checkbox" id="f_drv"' + ck('drives',false) + '>驱动器</label> 音频<select id="f_audio"><option value="0"' + (String(p.audiomode||0)==='0'?' selected':'') + '>本机播放</option><option value="1"' + (String(p.audiomode)==='1'?' selected':'') + '>远程播放</option><option value="2"' + (String(p.audiomode)==='2'?' selected':'') + '>不播放</option></select></div>'
   + '<div>体验：<select id="f_conn"><option value="7"' + (String(p.conntype||7)==='7'?' selected':'') + '>自动检测</option><option value="1"' + (String(p.conntype)==='1'?' selected':'') + '>调制解调器</option><option value="6"' + (String(p.conntype)==='6'?' selected':'') + '>LAN</option></select> <label><input type="checkbox" id="f_reconn"' + ck('autoreconnect',true) + '>断线自动重连</label></div>'
   + '<div>高级：认证<select id="f_auth"><option value="2"' + (String(p.authlevel||2)==='2'?' selected':'') + '>警告</option><option value="1"' + (String(p.authlevel)==='1'?' selected':'') + '>不连接</option><option value="0"' + (String(p.authlevel)==='0'?' selected':'') + '>直接连</option></select> 网关<input id="f_gw" placeholder="RD 网关(可空)" value="' + iv('gateway') + '"></div>'
   + '<div style="margin-top:6px"><button onclick="saveRdp()">保存(.json+.rdp)</button> <button class="ghost" onclick="editing=null;render()">取消</button></div></fieldset>';
}
function saveRdp(){
  var g = function(id){ return document.getElementById(id); };
  post({cmd:'rdpSave', profile:{
    name: g('f_name').value, host: g('f_host').value, port: g('f_port').value, username: g('f_user').value,
    width: g('f_w').value, height: g('f_h').value, fullscreen: g('f_full').checked, multimon: g('f_multi').checked,
    clipboard: g('f_clip').checked, printers: g('f_prn').checked, drives: g('f_drv').checked, audiomode: g('f_audio').value,
    conntype: g('f_conn').value, autoreconnect: g('f_reconn').checked, authlevel: g('f_auth').value, gateway: g('f_gw').value,
  }});
  editing = null;
}
window.addEventListener('message', function(ev){
  var m = ev.data || {};
  if (m.kind === 'homeData') { if (m.data && m.data.error) { /* 保留当前视图 */ } else S = m.data; render(); }
});
post({cmd:'homeInfo'});
</script></body></html>`;
}

function openHome(context) {
  if (homePanel) { homePanel.reveal(); return; }
  homePanel = vscode.window.createWebviewPanel("daoWinHome", "\u262f DAO \u5f52\u4e00\u4e3b\u9875 \u00b7 Windows \u603b\u63a7", vscode.ViewColumn.Active, { enableScripts: true, retainContextWhenHidden: true });
  homePanel.webview.html = homeHtml();
  homePanel.onDidDispose(() => { homePanel = null; });
  homePanel.webview.onDidReceiveMessage((msg) => handleHomeMessage(context, msg));
}

// 二合一统领(参照 devin-remote/dao-one): 子引擎 vendored 在 vendor/<名>/extension.js,
// 各自 activate 时锁到自己的子目录读资源; 其余字段透传。
function subContext(ctx, subDir) {
  const subPath = path.join(ctx.extensionPath, subDir);
  const subUri = vscode.Uri.file(subPath);
  return new Proxy(ctx, {
    get(target, prop) {
      if (prop === "extensionPath") return subPath;
      if (prop === "extensionUri") return subUri;
      if (prop === "asAbsolutePath") return (rel) => path.join(subPath, rel);
      const v = target[prop];
      return typeof v === "function" ? v.bind(target) : v;
    },
  });
}

const _vendorLoaded = [];

// ── 归一塑形分派器 ─────────────────────────────────────────────────────────
// 单一 Cascade 基底服务一切领域: 各领域子模块把本领域塑形器(wrap/status/toggle 或
// 领域画像 systemPrompt)登记进来, 宿主据活动模式(~/.dao/mode.json → domain:<app_id>)
// 择一分派; 无领域态或 native 时字节级直通(道并行而不相惖)。
const _domainShapers = new Map();
function _activeDomainApp() {
  try {
    const j = JSON.parse(fs.readFileSync(path.join(require("os").homedir(), ".dao", "mode.json"), "utf-8"));
    const id = j && j.mode && j.mode.id ? j.mode.id : j && j.mode;
    if (typeof id === "string" && id.indexOf("domain:") === 0) return id.slice("domain:".length);
  } catch (_) {}
  return null;
}
function installUnifiedShaperDispatcher(daoAiBase, log) {
  if (typeof daoAiBase.setPromptShaper !== "function") return;
  const dispatcher = {
    wrap(text, ctx) {
      const app = _activeDomainApp();
      const s = app && _domainShapers.get(app);
      if (!s) return text;
      try {
        if (typeof s.wrap === "function") { const o = s.wrap(text, ctx || {}); return typeof o === "string" ? o : text; }
      } catch (_) {}
      return text;
    },
    status() {
      const app = _activeDomainApp();
      const s = app && _domainShapers.get(app);
      if (s && typeof s.status === "function") { try { return s.status(); } catch (_) {} }
      return { mode: app ? "domain:" + app : "native", label: app ? "@" + app : "" };
    },
    toggle() {
      const app = _activeDomainApp();
      const s = app && _domainShapers.get(app);
      if (s && typeof s.toggle === "function") { try { return s.toggle(); } catch (_) {} }
    },
  };
  daoAiBase.setPromptShaper(dispatcher);
  // 领域子模块经此全局登记塑形器(折入模式下不再各自另起基底)。
  globalThis.__DAO_UNIFIED_HOST__ = {
    registerDomainShaper(app, shaper) {
      if (!app || !shaper) return;
      _domainShapers.set(app, shaper);
      log("✓ [归一分派] 领域塑形器登记: @" + app);
    },
  };
  log("✓ 归一塑形分派器就位 (单一 Cascade 基底 · 按模式分派领域)");
}

// 扫 vendor/*/extension.js 并依次折入激活(装了哪个领域模块就自动多出哪一路面板);
// 单个子引擎失败不阻断主体与其他子引擎。
async function activateVendorModules(context) {
  const root = path.join(context.extensionPath, "vendor");
  let names = [];
  try { names = fs.readdirSync(root).filter((n) => fs.existsSync(path.join(root, n, "extension.js"))); } catch (_) { return; }
  for (const n of names) {
    const dir = "vendor/" + n;
    try {
      const mod = require(path.join(root, n, "extension.js"));
      if (mod && typeof mod.activate === "function") {
        await mod.activate(subContext(context, dir));
        _vendorLoaded.push({ mod, name: n });
        log("✓ [子模块 " + n + "] 引擎就位 (" + dir + ")");
      } else log("✗ [子模块 " + n + "] 无 activate");
    } catch (e) { log("✗ [子模块 " + n + "] 启动失败: " + (e && e.stack ? e.stack : e)); }
  }
  if (names.length) log("子模块就绪 " + _vendorLoaded.length + "/" + names.length);
}

async function activate(context) {
  const sessionId = windowSessionId();
  log("DAO Windows Agent \u6fc0\u6d3b \u00b7 \u672c\u7a97\u53e3 = " + sessionId);
  setStatus(sessionId, "\u70b9\u51fb\u6253\u5f00 DAO \u684c\u9762");
  // AI 交互基底(dao-ai-base · Devin Desktop 同源): Cascade 三模式面板, 命名空间 daoWin.cascade*。
  // 归一枢纽: 全仓只此一个 Cascade 基底(得一以为天下正)。各领域子模块(FreeCAD/KiCad/嘉立创)
  // 折入时不再各自另起基底/代理(避免多面板碎片化), 而是把本领域塑形器登记到下方分派器,
  // 由宿主按活动模式(~/.dao/mode.json 的 domain:<app_id>)分派——一个基底, 一切领域随模式流转。
  try {
    const daoAiBase = require("./dao-ai-base");
    daoAiBase.activateDaoAiBase(context, { ns: "daoWin", log: (m) => log("[dao-ai-base] " + m) });
    installUnifiedShaperDispatcher(daoAiBase, log);
  } catch (e) { log("[dao-ai-base] 基底激活失败: " + (e && e.stack ? e.stack : e)); }
  // 提示词隔离替换引擎(dao-proxy-pro · Proxy Pro 同源薄片): 读 ~/.dao/mode.json 契约道化 SP。
  try {
    const daoProxyPro = require("./dao-proxy-pro");
    daoProxyPro.activateDaoProxyPro(context, { ns: "daoWin", log: (m) => log("[dao-proxy-pro] " + m) });
  } catch (e) { log("[dao-proxy-pro] 引擎激活失败: " + (e && e.stack ? e.stack : e)); }
  // 底层工具融合(官方并列层): 把自带 runtime 的 MCP 外壳注册进官方 mcp_config.json,
  // 四领域动词以官方 function-calling 工具身份与内建工具并列, 与提示词隔离/替换同炉。
  try {
    const daoMcp = require("./dao-mcp");
    const c0 = cfg();
    await daoMcp.activateDaoMcp(context, { pythonPath: c0.pythonPath, bridgeUrl: c0.bridgeUrl, token: c0.token, log: (m) => log("[dao-mcp] " + m) });
  } catch (e) { log("[dao-mcp] 工具层注册失败: " + (e && e.stack ? e.stack : e)); }
  // vscode_* IDE 对等面(历史四模块工具组): 命令/诊断/定义/引用/符号/打开/活动编辑器
  // 包成本地子插件 @ide → 机控桥扫描描述符后自动多出一路领域工作层。
  try {
    const ideTools = require("./dao-ide-tools");
    const c2 = cfg();
    _ideTools = await ideTools.startIdeTools({ vscode, token: c2.token, log: (m) => log("[dao-ide-tools] " + m) });
  } catch (e) { log("[dao-ide-tools] IDE 对等面启动失败: " + (e && e.stack ? e.stack : e)); }
  // 二合一子模块(FreeCAD / KiCad / 嘉立创EDA / HomeAssistant …): 构建时由 unify.js 折入 vendor/。
  try { await activateVendorModules(context); } catch (e) { log("子模块编排异常: " + (e && e.stack ? e.stack : e)); }
  // 启动即收编同装的 DAO 领域子插件 → 机控桥自动多出各路 @ 工作层
  try { const nsp = harvestSubplugins(path.join(context.extensionPath, "vendor")); if (nsp) log("已收编领域子插件 " + nsp + " 个"); } catch (e) { log("子插件收编异常: " + e.message); }

  context.subscriptions.push(
    vscode.commands.registerCommand("daoWin.home", () => openHome(context)),
    vscode.commands.registerCommand("daoWin.openDesktop", () => openDesktop(context)),
    vscode.commands.registerCommand("daoWin.openAccountDesktop", () => openAccountDesktop(context)),
    vscode.commands.registerCommand("daoWin.accountCreate", () => manageAccount(context, "create")),
    vscode.commands.registerCommand("daoWin.accountList", () => manageAccount(context, "list")),
    vscode.commands.registerCommand("daoWin.accountDestroy", () => manageAccount(context, "destroy")),
    vscode.commands.registerCommand("daoWin.openPanel", () => openPanel(context)),
    vscode.commands.registerCommand("daoWin.ask", () => openAsk(context)),
    vscode.commands.registerCommand("daoWin.health", async () => {
      const info = await ensureBridge(context);
      if (!info) { vscode.window.showErrorMessage("DAO: \u673a\u63a7\u6865\u4e0d\u53ef\u8fbe"); return; }
      const r = await apiCall(info.url, info.token, "GET", "/api/health");
      vscode.window.showInformationMessage("DAO \u6865 " + (r.body && r.body.ok ? "OK @ " + info.url : "\u5f02\u5e38"));
    }),
    vscode.commands.registerCommand("daoWin.ensureBridge", async () => {
      const info = await ensureBridge(context);
      vscode.window.showInformationMessage(info ? "DAO \u6865\u5df2\u8fde: " + info.url : "DAO \u6865\u4e0d\u53ef\u8fbe");
    }),
    vscode.commands.registerCommand("daoWin.switchMode", () => switchMode(context)),
    vscode.commands.registerCommand("daoWin.mcpRegister", async () => {
      try {
        const daoMcp = require("./dao-mcp");
        const c1 = cfg();
        const r = await daoMcp.activateDaoMcp(context, { pythonPath: c1.pythonPath, bridgeUrl: c1.bridgeUrl, token: c1.token, log: (m) => log("[dao-mcp] " + m) });
        vscode.window.showInformationMessage("DAO MCP 工具层" + (r.changed ? "已注册/刷新" : "已就绪(无变化)") + ": " + r.path);
      } catch (e) { vscode.window.showErrorMessage("DAO MCP 注册失败: " + e.message); }
    })
  );

  // 激活即后台连桥并为本窗口建隔离会话（零点击冷启动）
  const info = await ensureBridge(context);
  if (info) {
    try {
      await apiCall(info.url, info.token, "POST", "/api/session.create", { session_id: sessionId });
      setStatus(sessionId + " \u25cf", "\u6865\u5df2\u8fde " + info.url + " \u00b7 \u70b9\u51fb\u6253\u5f00\u684c\u9762");
      log("\u672c\u7a97\u53e3\u9694\u79bb\u4f1a\u8bdd\u5df2\u5c31\u7eea: " + sessionId);
      refreshModeStatus(context, info);
    } catch (e) { log("\u5efa\u4f1a\u8bdd\u5931\u8d25: " + e.message); }
  } else {
    setStatus(sessionId + " \u25cb", "\u6865\u672a\u8fde\uff08\u70b9\u51fb\u6253\u5f00\u684c\u9762\u91cd\u8bd5\uff09");
  }
}

function deactivate() {
  if (_ideTools) { try { _ideTools.stop(); } catch (e) {} _ideTools = null; }
  for (const v of _vendorLoaded) { try { v.mod.deactivate && v.mod.deactivate(); } catch (e) {} }
  if (spawnedBridge) { try { spawnedBridge.kill(); } catch (e) {} }
  for (const p of desktopPanels.values()) { try { p.dispose(); } catch (e) {} }
  desktopPanels.clear();
}

module.exports = { activate, deactivate };
