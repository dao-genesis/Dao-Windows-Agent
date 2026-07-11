/*
 * 归一外壳 /shell — 网页套网页(dao-one 骨架在本仓的落地)
 *
 * 与 devin-remote 的归一体系同构：单一外壳 = 带标签栏的迷你浏览器，
 * 每个板块一张平级并排的标签(iframe 子网页)。IDE webview 内能操作的，
 * 任意外部浏览器打开 http://127.0.0.1:<port>/shell 同样能操作 —— 归一。
 *
 * 板块(BOARDS)：
 *   home     🏠 主页仪表盘(桥接/显示路由/反代/工具面实时状态 + 快捷动作)
 *   freecad  🧊 FreeCAD 整窗(xpra X11 指令级路由 HTML5 客户端)
 *   bench    ⚙️ 归一工作台(桥接自带单网页 /ui：模型树/视口/控制台)
 *   proxy    🔀 Proxy Pro(本源观照/渠道配置/模型路由 · 复用 dao-proxy-pro 原生面板)
 */
const http = require("http");

const BOARD_META = {
  home: ["🏠", "主页"],
  freecad: ["🧊", "FreeCAD 整窗"],
  bench: ["⚙️", "归一工作台"],
  proxy: ["🔀", "Proxy Pro"],
};

let _server = null;
let _port = 0;
let _deps = null; // { bridgePort(), xpraPort, proxyHtml(), status() }

function probe(port, path_) {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}${path_ || "/"}`, { timeout: 1500 }, (res) => {
      res.resume(); resolve(res.statusCode && res.statusCode < 500);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
  });
}

function fetchJson(port, path_) {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}${path_}`, { timeout: 4000 }, (res) => {
      let b = ""; res.on("data", (c) => (b += c));
      res.on("end", () => { try { resolve(JSON.parse(b)); } catch (_) { resolve(null); } });
    });
    req.on("error", () => resolve(null));
    req.on("timeout", () => { req.destroy(); resolve(null); });
  });
}

function shellHtml() {
  const metaJson = JSON.stringify(BOARD_META);
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>☯ 归一 · DAO FreeCAD</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden; background: #16181d; color: #d5d9e0;
    font: 13px/1.5 system-ui, "Segoe UI", sans-serif; }
  #bar { display: flex; align-items: center; gap: 2px; height: 36px; padding: 0 8px;
    background: #1e2127; border-bottom: 1px solid #2c3038; overflow-x: auto; }
  #bar .brand { font-weight: 700; margin-right: 10px; white-space: nowrap; }
  .tab { padding: 5px 12px; border-radius: 6px 6px 0 0; cursor: pointer; user-select: none;
    white-space: nowrap; opacity: .65; border: 1px solid transparent; }
  .tab:hover { opacity: 1; }
  .tab.active { opacity: 1; background: #16181d; border-color: #2c3038; border-bottom-color: #16181d; }
  #frames { position: absolute; inset: 36px 0 0 0; }
  #frames iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; display: none; background: #16181d; }
  #frames iframe.active { display: block; }
</style></head><body>
<div id="bar"><span class="brand">☯ 归一</span></div>
<div id="frames"></div>
<script>
(function(){
  var META = ${metaJson};
  var bar = document.getElementById("bar"), frames = document.getElementById("frames");
  var cur = null, made = {};
  function open(key){
    if(cur === key) return;
    if(!made[key]){
      var f = document.createElement("iframe");
      f.id = "fr-" + key;
      f.src = "/board/" + key;
      f.allow = "clipboard-read; clipboard-write";
      frames.appendChild(f);
      made[key] = f;
    }
    Object.keys(made).forEach(function(k){ made[k].classList.toggle("active", k === key); });
    Array.prototype.forEach.call(bar.querySelectorAll(".tab"), function(t){
      t.classList.toggle("active", t.dataset.k === key);
    });
    cur = key;
    try { history.replaceState(null, "", "/shell#" + key); } catch(e) {}
  }
  Object.keys(META).forEach(function(k){
    var t = document.createElement("span");
    t.className = "tab"; t.dataset.k = k;
    t.textContent = META[k][0] + " " + META[k][1];
    t.onclick = function(){ open(k); };
    bar.appendChild(t);
  });
  open((location.hash || "#home").slice(1) in META ? (location.hash || "#home").slice(1) : "home");
})();
</script></body></html>`;
}

function homeHtml() {
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #16181d; color: #d5d9e0; font: 13px/1.6 system-ui, sans-serif; padding: 22px; }
  h1 { font-size: 17px; margin-bottom: 4px; } .sub { opacity: .6; margin-bottom: 18px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
  .card { background: #1e2127; border: 1px solid #2c3038; border-radius: 8px; padding: 14px; }
  .card h2 { font-size: 13px; margin-bottom: 8px; }
  .ok { color: #6fdb8c; } .bad { color: #e8705f; }
  .kv { display: flex; justify-content: space-between; margin: 2px 0; }
  .kv span:first-child { opacity: .65; }
  button { margin-top: 10px; margin-right: 6px; padding: 5px 12px; border: 1px solid #3a4150;
    background: #262b34; color: #d5d9e0; border-radius: 5px; cursor: pointer; }
  button:hover { background: #303743; }
  #log { margin-top: 16px; font-family: monospace; font-size: 12px; opacity: .7; white-space: pre-wrap; }
</style></head><body>
<h1>☯ 归一 · DAO FreeCAD 总控</h1>
<div class="sub">dao-desktop AI 底层 × Proxy Pro × FreeCAD 全模块 · 单网页归一外壳(浏览器 / IDE 面板同源)</div>
<div class="grid">
  <div class="card"><h2>🧠 FreeCAD 内核桥接</h2><div id="c-bridge">…</div>
    <button onclick="act('restartBridge')">启动/重启桥接</button></div>
  <div class="card"><h2>🖥 显示路由 (xpra)</h2><div id="c-xpra">…</div>
    <button onclick="act('fit')">面板适配主窗</button></div>
  <div class="card"><h2>🔀 Proxy Pro 反代</h2><div id="c-proxy">…</div></div>
  <div class="card"><h2>🛠 AI 工具面 (cad_agent)</h2><div id="c-tools">…</div></div>
</div>
<div id="log"></div>
<script>
function kv(k,v,cls){ return '<div class="kv"><span>'+k+'</span><span class="'+(cls||'')+'">'+v+'</span></div>'; }
function paint(s){
  document.getElementById('c-bridge').innerHTML =
    kv('状态', s.bridge.ok ? '在线' : '离线', s.bridge.ok ? 'ok' : 'bad') +
    kv('端口', s.bridge.port) +
    kv('FreeCAD', s.bridge.version || '—') +
    kv('文档', (s.bridge.documents || []).join(', ') || '(无)');
  document.getElementById('c-xpra').innerHTML =
    kv('状态', s.xpra.ok ? '在线' : '离线', s.xpra.ok ? 'ok' : 'bad') + kv('端口', s.xpra.port);
  document.getElementById('c-proxy').innerHTML =
    kv('反代', s.proxy.port ? ('127.0.0.1:' + s.proxy.port) : '未就绪', s.proxy.port ? 'ok' : 'bad') +
    kv('模块', '本源观照 / 渠道配置 / 模型路由');
  document.getElementById('c-tools').innerHTML =
    kv('op 总数', s.tools.count != null ? s.tools.count : '—', s.tools.count ? 'ok' : '') +
    kv('分组', s.tools.groups != null ? s.tools.groups : '—') +
    kv('MCP', 'dao-freecad (Cascade 注册)');
}
function refresh(){ fetch('/api/status').then(function(r){ return r.json(); }).then(paint).catch(function(){}); }
function act(op){
  var log = document.getElementById('log');
  log.textContent = '→ ' + op + ' …';
  fetch('/api/action', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({op:op}) })
    .then(function(r){ return r.json(); })
    .then(function(j){ log.textContent = '✓ ' + op + ': ' + JSON.stringify(j); setTimeout(refresh, 1500); })
    .catch(function(e){ log.textContent = '✗ ' + op + ': ' + e; });
}
refresh(); setInterval(refresh, 5000);
</script></body></html>`;
}

function iframeBoard(url, title) {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title>
<style>html,body{height:100%;margin:0;overflow:hidden;background:#16181d}iframe{width:100%;height:100%;border:0}</style>
</head><body><iframe src="${url}" allow="clipboard-read; clipboard-write"></iframe></body></html>`;
}

function emptyBoard(msg) {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{background:#16181d;color:#d5d9e0;font:13px system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
</style></head><body><div>${msg} <a href="" style="color:#6fa7ff">重试</a></div></body></html>`;
}

async function collectStatus() {
  const d = _deps;
  const bridgePort = d.bridgePort();
  const [st, spec, xpraOk] = await Promise.all([
    fetchJson(bridgePort, "/status"),
    fetchJson(bridgePort, "/toolspec"),
    probe(d.xpraPort, "/index.html"),
  ]);
  let proxyPort = 0;
  try { proxyPort = d.proxyPort() || 0; } catch (_) {}
  return {
    bridge: {
      ok: !!(st && st.ok), port: bridgePort,
      version: st && st.freecad_version ? st.freecad_version.slice(0, 3).filter(Boolean).join(".") : null,
      documents: (st && st.documents) || [],
    },
    xpra: { ok: xpraOk, port: d.xpraPort },
    proxy: { port: proxyPort },
    tools: {
      count: spec && spec.ok ? spec.count : null,
      groups: spec && spec.ok && spec.groups ? spec.groups.length : null,
    },
  };
}

function send(res, code, type, body) {
  res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*" });
  res.end(body);
}

/**
 * 启动归一外壳服务器。deps:
 *   bridgePort() → 桥接端口; xpraPort → xpra HTML5 端口;
 *   proxyPort() → dao-proxy-pro 反代端口(0=未起); proxyHtml() → Proxy Pro 三模块面板 HTML;
 *   actions: { restartBridge(), fit() }
 */
function startShell(port, deps, log) {
  _deps = deps;
  if (_server) return Promise.resolve(_port);
  return new Promise((resolve) => {
    const tryListen = (pt, left) => {
    const srv = http.createServer(async (req, res) => {
      try {
        const u = new URL(req.url, "http://x");
        const p = u.pathname;
        if (p === "/" || p === "/shell") return send(res, 200, "text/html; charset=utf-8", shellHtml());
        if (p === "/board/home") return send(res, 200, "text/html; charset=utf-8", homeHtml());
        if (p === "/board/freecad")
          return send(res, 200, "text/html; charset=utf-8", iframeBoard(
            `http://127.0.0.1:${deps.xpraPort}/index.html?reconnect=true&sound=false&clipboard=true&floating_menu=no&autohide=1&video=false`,
            "FreeCAD 整窗归一"));
        if (p === "/board/bench")
          return send(res, 200, "text/html; charset=utf-8", iframeBoard(
            `http://127.0.0.1:${deps.bridgePort()}/ui?ts=${Date.now()}`, "归一工作台"));
        if (p === "/board/proxy") {
          let html = null;
          try { html = deps.proxyHtml(); } catch (_) {}
          return send(res, 200, "text/html; charset=utf-8",
            html || emptyBoard("🔀 Proxy Pro 未就绪(反代未启动) —— 不影响其余板块。"));
        }
        if (p === "/api/health") return send(res, 200, "application/json", JSON.stringify({ ok: true, app: "dao-freecad-shell" }));
        if (p === "/api/status") return send(res, 200, "application/json", JSON.stringify(await collectStatus()));
        if (p === "/api/action" && req.method === "POST") {
          let b = "";
          req.on("data", (c) => (b += c));
          req.on("end", async () => {
            try {
              const j = JSON.parse(b || "{}");
              const fn = deps.actions[j.op];
              if (!fn) return send(res, 400, "application/json", JSON.stringify({ ok: false, error: "未知动作 " + j.op }));
              const r = await fn();
              send(res, 200, "application/json", JSON.stringify({ ok: true, result: r === undefined ? null : r }));
            } catch (e) { send(res, 500, "application/json", JSON.stringify({ ok: false, error: String(e && e.message || e) })); }
          });
          return;
        }
        send(res, 404, "text/plain", "not found");
      } catch (e) {
        try { send(res, 500, "text/plain", String(e && e.stack || e)); } catch (_) {}
      }
    });
    srv.on("error", (e) => {
      // 道并行而不相悖：端口被占(如 dao-vsix 本地 API)时自动后退相邻端口
      if (e && e.code === "EADDRINUSE" && left > 0) {
        log && log("⚠ 端口 " + pt + " 被占，后退到 " + (pt + 1));
        return tryListen(pt + 1, left - 1);
      }
      log && log("✗ 归一外壳端口 " + pt + " 启动失败: " + e.message);
      resolve(0);
    });
    srv.listen(pt, "127.0.0.1", () => {
      _server = srv; _port = pt;
      log && log("✓ 归一外壳 /shell 在线: http://127.0.0.1:" + pt + "/shell");
      resolve(pt);
    });
    };
    tryListen(port, 9);
  });
}

function stopShell() {
  if (_server) { try { _server.close(); } catch (_) {} _server = null; _port = 0; }
}

function shellPort() { return _port; }

module.exports = { startShell, stopShell, shellPort, BOARD_META };
