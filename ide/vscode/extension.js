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

function harvestSubplugins() {
  let dir;
  try {
    dir = subpluginDir();
    fs.mkdirSync(dir, { recursive: true });
  } catch (e) { log("子插件发现目录创建失败: " + e.message); return 0; }
  let n = 0;
  for (const ext of vscode.extensions.all) {
    const pj = ext.packageJSON || {};
    const spec = pj.daoSubplugin || (pj.contributes && pj.contributes.daoSubplugin);
    if (!spec || !spec.app_id || !Array.isArray(spec.verbs) || !spec.verbs.length) continue;
    const desc = Object.assign({ source: "vscode:" + ext.id, layer: "domain" }, spec);
    if (!desc.invoke_url) { log("子插件 " + ext.id + " 缺 invoke_url，跳过"); continue; }
    try {
      fs.writeFileSync(path.join(dir, desc.app_id + ".json"), JSON.stringify(desc, null, 2), "utf-8");
      n++;
      log("收编子插件 @" + (desc.mention || desc.app_id) + " ← " + ext.id);
    } catch (e) { log("写子插件描述符失败 " + ext.id + ": " + e.message); }
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
#bar{padding:4px 10px;background:#24242a;display:flex;align-items:center;gap:10px;font-size:12px;border-bottom:1px solid #333;flex-shrink:0}
#bar button{padding:3px 8px;border:none;border-radius:3px;background:var(--vscode-button-background,#3c8dbc);color:var(--vscode-button-foreground,#fff);cursor:pointer;font-size:11px}
#status{flex:1;text-align:right;opacity:.7}
#desktop{flex:1;overflow:hidden;position:relative}
#desktop>div{position:absolute!important;top:0;left:0}
#overlay{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;font-size:14px;opacity:.6}
</style></head><body>
<div id="bar">
  <b>\u2630 DAO \u684c\u9762</b>
  <select id="acct" title="\u8d26\u53f7\uff08\u591a RDP \u4e00\u8def\u4e00\u684c\u9762\uff09" onchange="onAcctChange()"></select>
  <button onclick="doConnect()">\u8fde\u63a5</button>
  <button onclick="doDisconnect()">\u65ad\u5f00</button>
  <button onclick="doFullscreen()">\u2922</button>
  <span id="status">\u672a\u8fde\u63a5</span>
</div>
<div id="desktop"><div id="overlay">\u70b9\u51fb\u300c\u8fde\u63a5\u300d\u5373\u53ef\u770b\u5230 Windows \u684c\u9762</div></div>
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
let client = null;
let connecting = false;
let userDisconnected = false;
let retries = 0;
let retryTimer = null;
const MAX_RETRIES = 5;
let lastLocalClip = null;
let lastRemoteClip = null;

// \u586b\u5145\u8d26\u53f7\u4e0b\u62c9\uff1b\u9009\u4e2d\u672c\u9762\u677f\u7ed1\u5b9a\u8d26\u53f7\uff0c\u5207\u5230\u5176\u4ed6\u8d26\u53f7\u5219\u65b0\u5f00/\u5207\u5230\u90a3\u4e00\u8def\u9762\u677f\u3002
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
  acctEl.value = ACCOUNT; // \u672c\u9762\u677f\u4ecd\u7ed1\u5b9a\u539f\u8d26\u53f7
}

function setStatus(t, c) { statusEl.textContent = t; statusEl.style.color = c || '#e0e0e0'; }

async function doConnect() {
  if (connecting) return;
  connecting = true;
  userDisconnected = false;
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  doDisconnect(true);
  setStatus('\u53d6 token...', '#ffcc00');
  const w = container.clientWidth;
  const h = container.clientHeight;
  let tokenData;
  try {
    const q = ACCOUNT ? ('account=' + encodeURIComponent(ACCOUNT)) : ('ide=' + IDE_SESSION);
    const r = await fetch(TUNNEL_HTTP + '/token?' + q + '&width=' + w + '&height=' + h);
    tokenData = await r.json();
    if (tokenData.error) { setStatus('\u4ee4\u724c: ' + tokenData.error, '#ff4444'); connecting = false; return; }
  } catch (e) { setStatus('\u4ee4\u724c\u83b7\u53d6\u5931\u8d25: ' + e.message, '#ff4444'); connecting = false; return; }
  let wsHost = '127.0.0.1', wsScheme = 'ws';
  try { const tu = new URL(TUNNEL_HTTP); wsHost = tu.hostname || wsHost; wsScheme = (tu.protocol === 'https:') ? 'wss' : 'ws'; } catch (e) {}
  const wsUrl = wsScheme + '://' + wsHost + ':' + TUNNEL_WS_PORT + '/?token=' + encodeURIComponent(tokenData.token);
  setStatus('\u5efa\u7acb WS \u96a7\u9053...', '#ffcc00');
  const tunnel = new Guacamole.WebSocketTunnel(wsUrl);
  client = new Guacamole.Client(tunnel);
  const display = client.getDisplay();
  var ov = document.getElementById('overlay'); if (ov) ov.remove();
  container.innerHTML = '';
  container.appendChild(display.getElement());
  // \u9f20\u6807（\u6309\u663e\u793a\u7f29\u653e\u6362\u7b97\u56de\u771f\u5b9e\u5750\u6807）
  const mouse = new Guacamole.Mouse(display.getElement());
  mouse.onEach(['mousedown','mousemove','mouseup'], function(e) {
    if (!client) return;
    var s = display.getScale() || 1;
    var st = e.state;
    if (s !== 1) st = new Guacamole.Mouse.State(st.x / s, st.y / s, st.left, st.middle, st.right, st.up, st.down);
    client.sendMouseState(st, true);
  });
  // \u952e\u76d8
  const keyboard = new Guacamole.Keyboard(document);
  keyboard.onkeydown = function(k) { if (client) client.sendKeyEvent(1, k); };
  keyboard.onkeyup = function(k) { if (client) client.sendKeyEvent(0, k); };
  // \u81ea\u9002\u5e94\u7f29\u653e
  display.onresize = function(dw, dh) {
    const scale = Math.min(container.clientWidth / dw, container.clientHeight / dh, 1);
    display.scale(scale);
  };
  // \u526a\u8d34\u677f\uff1a\u8fdc\u7aef\u2192\u672c\u5730\uff08\u7ecf\u6269\u5c55\u5bbf\u4e3b\u5199 vscode \u526a\u8d34\u677f\uff09
  client.onclipboard = function(stream, mimetype) {
    // 注意：本段位于模板字面量内，\\/ 会被吞成 /，禁用含斜杠的正则字面量（真机踩坑：SyntaxError 令整段脚本报废）。
    if (mimetype.indexOf('text/') !== 0) { try { stream.sendAck('OK', 0); } catch(e) {} return; }
    var reader = new Guacamole.StringReader(stream);
    var data = '';
    reader.ontext = function(t) { data += t; };
    reader.onend = function() {
      if (data && data !== lastLocalClip) { lastRemoteClip = data; vscodeApi.postMessage({type:'clipboard', text: data}); }
    };
  };
  client.onstatechange = function(state) {
    var names = ['\u7a7a\u95f2','\u6b63\u5728\u8fde\u63a5...','\u7b49\u5f85\u4e2d...','\u5df2\u8fde\u63a5 \u25cf','\u6b63\u5728\u65ad\u5f00...','\u5df2\u65ad\u5f00'];
    var colors = ['#999','#ffcc00','#ffcc00','#44ff44','#ff8800','#ff4444'];
    setStatus(names[state] || state, colors[state]);
    vscodeApi.postMessage({type:'state', state: state});
    if (state === 3) { retries = 0; vscodeApi.postMessage({type:'readClipboard'}); }
    // \u975e\u7528\u6237\u4e3b\u52a8\u65ad\u5f00 \u2192 \u9000\u907f\u91cd\u8fde
    if (state === 5 && !userDisconnected) {
      if (retries < MAX_RETRIES) {
        var delay = Math.min(2000 * Math.pow(2, retries), 15000);
        retries++;
        setStatus('\u65ad\u7ebf\uff0c' + (delay/1000) + 's \u540e\u91cd\u8fde(' + retries + '/' + MAX_RETRIES + ')...', '#ff8800');
        if (retryTimer) clearTimeout(retryTimer);
        retryTimer = setTimeout(function(){ doConnect(); }, delay);
      } else {
        setStatus('\u5df2\u65ad\u5f00\uff08\u91cd\u8fde\u6b21\u6570\u8017\u5c3d\uff0c\u70b9\u300c\u8fde\u63a5\u300d\u624b\u52a8\u91cd\u8bd5\uff09', '#ff4444');
      }
    }
  };
  client.onerror = function(s) { setStatus('\u9519\u8bef: ' + (s.message || s.code || ''), '#ff4444'); };
  tunnel.onerror = function(s) { setStatus('\u96a7\u9053\u9519\u8bef: ' + (s && (s.message || s.code) || ''), '#ff4444'); };
  client.connect();
  connecting = false;
}

function doDisconnect(isReconnect) {
  if (!isReconnect) { userDisconnected = true; if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; } }
  if (client) { try { client.disconnect(); } catch(e) {} client = null; }
}

// \u526a\u8d34\u677f\uff1a\u672c\u5730\u2192\u8fdc\u7aef\uff08\u6269\u5c55\u5bbf\u4e3b\u56de\u4f20 vscode \u526a\u8d34\u677f\u5185\u5bb9\uff09
function sendClipboard(text) {
  if (!client || typeof text !== 'string' || !text || text === lastRemoteClip) return;
  lastLocalClip = text;
  try {
    var stream = client.createClipboardStream('text/plain');
    var writer = new Guacamole.StringWriter(stream);
    writer.sendText(text);
    writer.sendEnd();
  } catch (e) {}
}
window.addEventListener('message', function(ev) {
  var msg = ev.data || {};
  if (msg.type === 'clipboardData') sendClipboard(msg.text);
});
// \u9762\u677f\u91cd\u65b0\u83b7\u7126\u65f6\u540c\u6b65\u672c\u5730\u526a\u8d34\u677f\u5230\u8fdc\u7aef
window.addEventListener('focus', function() { if (client) vscodeApi.postMessage({type:'readClipboard'}); });

function doFullscreen() { vscodeApi.postMessage({type:'fullscreen'}); }

// \u6fc0\u6d3b\u5373\u81ea\u52a8\u8fde\u63a5
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

async function activate(context) {
  const sessionId = windowSessionId();
  log("DAO Windows Agent \u6fc0\u6d3b \u00b7 \u672c\u7a97\u53e3 = " + sessionId);
  setStatus(sessionId, "\u70b9\u51fb\u6253\u5f00 DAO \u684c\u9762");
  // 启动即收编同装的 DAO 领域子插件 → 机控桥自动多出各路 @ 工作层
  try { const nsp = harvestSubplugins(); if (nsp) log("已收编领域子插件 " + nsp + " 个"); } catch (e) { log("子插件收编异常: " + e.message); }

  context.subscriptions.push(
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
    })
  );

  // 激活即后台连桥并为本窗口建隔离会话（零点击冷启动）
  const info = await ensureBridge(context);
  if (info) {
    try {
      await apiCall(info.url, info.token, "POST", "/api/session.create", { session_id: sessionId });
      setStatus(sessionId + " \u25cf", "\u6865\u5df2\u8fde " + info.url + " \u00b7 \u70b9\u51fb\u6253\u5f00\u684c\u9762");
      log("\u672c\u7a97\u53e3\u9694\u79bb\u4f1a\u8bdd\u5df2\u5c31\u7eea: " + sessionId);
    } catch (e) { log("\u5efa\u4f1a\u8bdd\u5931\u8d25: " + e.message); }
  } else {
    setStatus(sessionId + " \u25cb", "\u6865\u672a\u8fde\uff08\u70b9\u51fb\u6253\u5f00\u684c\u9762\u91cd\u8bd5\uff09");
  }
}

function deactivate() {
  if (spawnedBridge) { try { spawnedBridge.kill(); } catch (e) {} }
  for (const p of desktopPanels.values()) { try { p.dispose(); } catch (e) {} }
  desktopPanels.clear();
}

module.exports = { activate, deactivate };
