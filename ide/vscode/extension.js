"use strict";
// DAO Windows Agent · VSCode 前端
// 本源：每个 IDE 窗口 = 一个单账号零配置隔离会话（类多RDP效果）。
// 插件不投屏，而是经机控桥（bridge/ REST）直达级别①②③——把整台 Windows 做进 IDE。
const vscode = require("vscode");
const http = require("http");
const cp = require("child_process");
const path = require("path");
const crypto = require("crypto");

let output;
let statusItem;
let panel;
let spawnedBridge = null; // 自启的本地桥子进程
let activeBridgeUrl = null; // 实际连上的桥地址

function cfg() {
  const c = vscode.workspace.getConfiguration("daoWin");
  return {
    bridgeUrl: (c.get("bridgeUrl") || "http://127.0.0.1:9920").replace(/\/$/, ""),
    token: c.get("token") || "",
    autostart: c.get("autostart") !== false,
    pythonPath: c.get("pythonPath") || "python",
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
    statusItem.command = "daoWin.openPanel";
    statusItem.show();
  }
  statusItem.text = "$(vm) DAO " + text;
  statusItem.tooltip = tooltip || "DAO Windows Agent · 本窗口=隔离会话";
}

// —— 面板 webview（一键按钮 + 参数输入，桥的所有 /api 动作全覆盖）——
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
  panel = vscode.window.createWebviewPanel("daoWinPanel", "DAO 虚拟机面板", vscode.ViewColumn.Active, { enableScripts: true, retainContextWhenHidden: true });
  panel.webview.html = panelHtml(sessionId);
  panel.onDidDispose(() => { panel = null; });
  panel.webview.onDidReceiveMessage((msg) => handlePanelMessage(context, msg));
}

async function activate(context) {
  const sessionId = windowSessionId();
  log("DAO Windows Agent 激活 · 本窗口隔离会话 = " + sessionId);
  setStatus(sessionId, "点击打开 DAO 虚拟机面板");

  context.subscriptions.push(
    vscode.commands.registerCommand("daoWin.openPanel", () => openPanel(context)),
    vscode.commands.registerCommand("daoWin.health", async () => {
      const info = await ensureBridge(context);
      if (!info) { vscode.window.showErrorMessage("DAO: 机控桥不可达"); return; }
      const r = await apiCall(info.url, info.token, "GET", "/api/health");
      vscode.window.showInformationMessage("DAO 桥 " + (r.body && r.body.ok ? "OK @ " + info.url : "异常"));
    }),
    vscode.commands.registerCommand("daoWin.ensureBridge", async () => {
      const info = await ensureBridge(context);
      vscode.window.showInformationMessage(info ? "DAO 桥已连: " + info.url : "DAO 桥不可达");
    })
  );

  // 激活即后台连桥并为本窗口建隔离会话（零点击冷启动）
  const info = await ensureBridge(context);
  if (info) {
    try {
      await apiCall(info.url, info.token, "POST", "/api/session.create", { session_id: sessionId });
      setStatus(sessionId + " ●", "桥已连 " + info.url + " · 会话就绪");
      log("本窗口隔离会话已就绪: " + sessionId);
    } catch (e) { log("建会话失败: " + e.message); }
  } else {
    setStatus(sessionId + " ○", "桥未连（点击打开面板重试）");
  }
}

function deactivate() {
  if (spawnedBridge) { try { spawnedBridge.kill(); } catch (e) {} }
}

module.exports = { activate, deactivate };
