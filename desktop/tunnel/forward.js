"use strict";
// ☯ 后端换机 · TCP ↔ WebSocket 转发对（把桌面路由的 RDP 目标换成任意远端机，含用户本地电脑）
//
// 本源：桌面路由链路（Webview → 本隧道 → guacd → RDP）里 guacd 只会拨 TCP。
// 要把"后端"从本机 QEMU 靶机换成用户本地电脑（经 DAO Bridge/CloudFlare 这类 HTTP/WS 穿透），
// 需要一对转发件把 RDP 的原始 TCP 字节流封进 WebSocket：
//
//   guacd ── TCP ──► connector(本机 127.0.0.1:<port>)
//                        │ ws(s)://<穿透公网URL>/rdp?token=…（Bearer 鉴权）
//                        ▼
//                    agent(用户机/远端机) ── TCP ──► 127.0.0.1:3389（远端 RDP）
//
// agent 跑在远端机（由 dao-vsix 插件宿主或独立 node 进程拉起，经既有穿透通道暴露）；
// connector 跑在隧道旁，惰性起监听，把 guacd 的连接逐条搬运到远端。
// 诚实边界：转发只搬字节，不解 RDP；时延/带宽受穿透通道制约，跨公网桌面交互体验
// 取决于通道 RTT（本地局域网/中继质量），转发层本身不额外缓冲。
//
// 账号注册表（accounts.json）声明远端机后端：
//   { "user-pc": { "username": "u", "password": "p",
//                  "via": "wss://<公网URL>/rdp", "viaToken": "<Bearer>" } }
// 铸 token 时经 ensureConnector(via) 惰性起本地口，并把目标重写为 127.0.0.1:<口>。

const net = require("net");
const { WebSocket, WebSocketServer } = require("ws");

// —— agent（远端机侧）：WS 服务 → 本地 TCP 目标 ——
// opts: { port, token, targetHost="127.0.0.1", targetPort=3389, host="127.0.0.1" }
function startAgent(opts) {
  const targetHost = opts.targetHost || "127.0.0.1";
  const targetPort = parseInt(opts.targetPort || 3389, 10);
  const wss = new WebSocketServer({
    port: opts.port,
    host: opts.host || "127.0.0.1",
    verifyClient: (info) => authOk(info.req, opts.token),
  });
  wss.on("connection", (ws) => {
    const sock = net.connect(targetPort, targetHost);
    pipeWsTcp(ws, sock);
  });
  return wss;
}

function authOk(req, token) {
  if (!token) return true;
  const h = String(req.headers["authorization"] || "");
  if (h === `Bearer ${token}`) return true;
  try {
    const u = new URL(req.url, "http://localhost");
    return u.searchParams.get("token") === token;
  } catch (e) {
    return false;
  }
}

// —— WS ↔ TCP 双向搬运（含半开/异常对称收尾，防悬挂连接泄漏）——
function pipeWsTcp(ws, sock) {
  sock.on("connect", () => {
    ws.on("message", (data) => sock.write(data));
    ws.on("close", () => sock.destroy());
    ws.on("error", () => sock.destroy());
    sock.on("data", (buf) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(buf);
    });
    sock.on("close", () => ws.close());
    sock.on("error", () => ws.close());
  });
  sock.on("error", () => {
    try { ws.close(); } catch (e) { /* 已关 */ }
  });
}

// —— connector（隧道侧）：本地 TCP 监听 → 远端 WS ——
// opts: { listenPort=0(随机), peerUrl, token, host="127.0.0.1" }
// 返回 Promise<net.Server>（server.address().port 为实际口）。
function startConnector(opts) {
  const server = net.createServer((sock) => {
    sock.pause();
    const headers = opts.token ? { Authorization: `Bearer ${opts.token}` } : {};
    const ws = new WebSocket(opts.peerUrl, { headers });
    ws.on("open", () => {
      sock.resume();
      sock.on("data", (buf) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(buf);
      });
      sock.on("close", () => ws.close());
      sock.on("error", () => ws.close());
      ws.on("message", (data) => sock.write(data));
      ws.on("close", () => sock.destroy());
      ws.on("error", () => sock.destroy());
    });
    ws.on("error", () => sock.destroy());
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(opts.listenPort || 0, opts.host || "127.0.0.1", () => resolve(server));
  });
}

// —— 惰性 connector 池：同一 via(远端 WS 端点) 全程只起一个本地口，多分身共用 ——
const _connectors = new Map(); // via → Promise<net.Server>

function ensureConnector(via, token) {
  if (!_connectors.has(via)) {
    _connectors.set(
      via,
      startConnector({ peerUrl: via, token }).catch((e) => {
        _connectors.delete(via); // 起监听失败不缓存失败态，下次可重试
        throw e;
      })
    );
  }
  return _connectors.get(via);
}

async function closeConnectors() {
  const all = Array.from(_connectors.values());
  _connectors.clear();
  await Promise.all(
    all.map((p) =>
      p.then((s) => new Promise((r) => s.close(r))).catch(() => {})
    )
  );
}

// 目标含 via（远端 WS 端点）→ 重写为本地 connector 口；否则原样返回。
async function resolveTarget(target) {
  if (!target || !target.via) return target;
  const server = await ensureConnector(target.via, target.viaToken);
  const out = Object.assign({}, target, {
    hostname: "127.0.0.1",
    port: String(server.address().port),
  });
  delete out.via;
  delete out.viaToken;
  return out;
}

module.exports = { startAgent, startConnector, ensureConnector, closeConnectors, resolveTarget };

// —— CLI（远端机侧一键起 agent）——
//   node forward.js agent --port 19389 --token <Bearer> [--target 127.0.0.1:3389] [--host 127.0.0.1]
// 经既有穿透通道（CloudFlare/Worker 中继）把该口暴露为公网 wss 后，
// 在 accounts.json 用 via/viaToken 指向它即可完成后端换机。
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args[0] !== "agent") {
    console.error("用法: node forward.js agent --port <口> --token <Bearer> [--target host:port] [--host 绑定地址]");
    process.exit(2);
  }
  const opt = {};
  for (let i = 1; i < args.length; i += 2) opt[args[i].replace(/^--/, "")] = args[i + 1];
  const [th, tp] = String(opt.target || "127.0.0.1:3389").split(":");
  const agent = startAgent({
    port: parseInt(opt.port || "19389", 10),
    host: opt.host || "127.0.0.1",
    token: opt.token,
    targetHost: th,
    targetPort: parseInt(tp, 10),
  });
  agent.on("listening", () => {
    const a = agent.address();
    console.log(`[forward] agent 就绪 ws://${a.address}:${a.port} → ${th}:${tp}` + (opt.token ? "（Bearer 鉴权）" : "（无鉴权，仅限内网）"));
  });
}
