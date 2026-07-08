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
let desktopPanel;    // 桌面路由面板（主前端）
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

// —— 桌面路由面板（主前端：guacamole-common-js canvas → WS 隧道 → guacd → RDP 会话）——
function desktopHtml(context, sessionId, tunnelHttpUrl, tunnelWsPort) {
  const guacUri = desktopPanel
    ? desktopPanel.webview.asWebviewUri(vscode.Uri.joinPath(context.extensionUri, "media", "guacamole-common.min.js"))
    : "";
  const cspSource = desktopPanel ? desktopPanel.webview.cspSource : "";
  const cspSrc = "default-src 'none'; script-src 'unsafe-inline' " + cspSource + "; style-src 'unsafe-inline'; connect-src ws://127.0.0.1:* http://127.0.0.1:* ws://localhost:* http://localhost:*; img-src data:;";
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
  <span style="opacity:.5">${sessionId}</span>
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
const vscodeApi = acquireVsCodeApi();
const container = document.getElementById('desktop');
const statusEl = document.getElementById('status');
let client = null;

function setStatus(t, c) { statusEl.textContent = t; statusEl.style.color = c || '#e0e0e0'; }

async function doConnect() {
  doDisconnect();
  setStatus('\u53d6 token...', '#ffcc00');
  const w = container.clientWidth;
  const h = container.clientHeight;
  let tokenData;
  try {
    const r = await fetch(TUNNEL_HTTP + '/token?ide=' + IDE_SESSION + '&width=' + w + '&height=' + h);
    tokenData = await r.json();
  } catch (e) { setStatus('\u4ee4\u724c\u83b7\u53d6\u5931\u8d25: ' + e.message, '#ff4444'); return; }
  const wsUrl = 'ws://127.0.0.1:' + TUNNEL_WS_PORT + '/?token=' + encodeURIComponent(tokenData.token);
  setStatus('\u5efa\u7acb WS \u96a7\u9053...', '#ffcc00');
  const tunnel = new Guacamole.WebSocketTunnel(wsUrl);
  client = new Guacamole.Client(tunnel);
  const display = client.getDisplay();
  document.getElementById('overlay').remove();
  container.appendChild(display.getElement());
  // \u9f20\u6807
  const mouse = new Guacamole.Mouse(display.getElement());
  mouse.onEach(['mousedown','mousemove','mouseup'], function(e) { client.sendMouseState(e.state, true); });
  // \u952e\u76d8
  const keyboard = new Guacamole.Keyboard(document);
  keyboard.onkeydown = function(k) { client.sendKeyEvent(1, k); };
  keyboard.onkeyup = function(k) { client.sendKeyEvent(0, k); };
  // \u81ea\u9002\u5e94\u7f29\u653e
  display.onresize = function(dw, dh) {
    const scale = Math.min(container.clientWidth / dw, container.clientHeight / dh, 1);
    display.scale(scale);
  };
  client.onstatechange = function(state) {
    var names = ['\u7a7a\u95f2','\u6b63\u5728\u8fde\u63a5...','\u7b49\u5f85\u4e2d...','\u5df2\u8fde\u63a5 \u25cf','\u6b63\u5728\u65ad\u5f00...','\u5df2\u65ad\u5f00'];
    var colors = ['#999','#ffcc00','#ffcc00','#44ff44','#ff8800','#ff4444'];
    setStatus(names[state] || state, colors[state]);
    vscodeApi.postMessage({type:'state', state: state});
  };
  client.onerror = function(s) { setStatus('\u9519\u8bef: ' + (s.message || s.code || ''), '#ff4444'); };
  client.connect();
}

function doDisconnect() {
  if (client) { try { client.disconnect(); } catch(e) {} client = null; }
}

function doFullscreen() { vscodeApi.postMessage({type:'fullscreen'}); }

// \u6fc0\u6d3b\u5373\u81ea\u52a8\u8fde\u63a5
setTimeout(doConnect, 300);
</script></body></html>`;
}

function openDesktop(context) {
  const sessionId = windowSessionId();
  const c = cfg();
  if (desktopPanel) { desktopPanel.reveal(); return; }
  desktopPanel = vscode.window.createWebviewPanel(
    "daoWinDesktop", "DAO \u684c\u9762 \u00b7 " + sessionId, vscode.ViewColumn.Active,
    { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "media")] }
  );
  desktopPanel.webview.html = desktopHtml(context, sessionId, c.tunnelHttpUrl, c.tunnelWsPort);
  desktopPanel.onDidDispose(() => { desktopPanel = null; });
  desktopPanel.webview.onDidReceiveMessage((msg) => {
    if (msg.type === "state" && msg.state === 3) {
      setStatus(sessionId + " \u25cf", "\u684c\u9762\u5df2\u8fde " + c.tunnelHttpUrl);
    }
    if (msg.type === "fullscreen") {
      vscode.commands.executeCommand("workbench.action.toggleEditorWidths");
    }
  });
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

async function activate(context) {
  const sessionId = windowSessionId();
  log("DAO Windows Agent \u6fc0\u6d3b \u00b7 \u672c\u7a97\u53e3 = " + sessionId);
  setStatus(sessionId, "\u70b9\u51fb\u6253\u5f00 DAO \u684c\u9762");

  context.subscriptions.push(
    vscode.commands.registerCommand("daoWin.openDesktop", () => openDesktop(context)),
    vscode.commands.registerCommand("daoWin.openPanel", () => openPanel(context)),
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
  if (desktopPanel) { try { desktopPanel.dispose(); } catch (e) {} }
}

module.exports = { activate, deactivate };
