"use strict";
// ☯ 桌面级路由控制面 · WebSocket ↔ guacd 隧道（正本清源·路线A）
//
// 本源：IDE 面板里直接就是整台 Windows 的桌面本体（类多 RDP 的一路真实会话），
// 不是投屏截图流。链路：
//
//   VSCode Webview(<canvas> + guacamole-common-js)
//        │  ws://127.0.0.1:4823/?token=<加密连接参数>
//        ▼
//   本隧道(guacamole-lite)  ── guac 协议 ──►  guacd(默认 4822)  ── RDP ──►  Windows 会话
//
// 每个 IDE 窗口按 ide_<hash> 稳定映射到一路 RDP 会话（见 sessions.json / 环境变量）。
// RDP 凭据只以密文形式经 token 下发，浏览器侧永不见明文（guacamole-lite AES-256-CBC）。
//
//   node server.js            # 起隧道(4823) + 令牌铸造 HTTP(4824)
// 环境变量：
//   DAO_GUAC_WS_PORT   隧道 WS 端口（默认 4823）
//   DAO_GUAC_HTTP_PORT 令牌铸造 HTTP 端口（默认 4824）
//   DAO_GUACD_HOST/PORT guacd 地址（默认 127.0.0.1:4822）
//   DAO_GUAC_KEY       token 加解密密钥（32 字节；缺省用内置实验密钥）
//   DAO_RDP_HOST/PORT  默认 RDP 目标（默认 127.0.0.1:13389，即冷启动 hostfwd→guest:3389）
//   DAO_RDP_USER/PASS  默认 RDP 凭据（默认 dao/Dao@2026!，仅限本地实验靶机）
//   DAO_SESSIONS_JSON  会话映射文件（ide_<hash> → RDP 目标）路径

const http = require("http");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const GuacamoleLite = require("guacamole-lite");

const WS_PORT = parseInt(process.env.DAO_GUAC_WS_PORT || "4823", 10);
const HTTP_PORT = parseInt(process.env.DAO_GUAC_HTTP_PORT || "4824", 10);
// 监听地址：默认仅回环（本机 IDE）；跨机/跨 VM（如 QEMU guest 经 10.0.2.2 回连宿主）设 0.0.0.0。
const BIND = process.env.DAO_GUAC_BIND || "127.0.0.1";
const GUACD_HOST = process.env.DAO_GUACD_HOST || "127.0.0.1";
const GUACD_PORT = parseInt(process.env.DAO_GUACD_PORT || "4822", 10);

// token 加解密密钥（必须 32 字节）。实验缺省值仅用于本地靶机；生产经环境变量注入。
const KEY = (process.env.DAO_GUAC_KEY || "dao-benyuan-desktop-routing-2026").padEnd(32, "0").slice(0, 32);
const CIPHER = "AES-256-CBC";

const DEFAULT_RDP = {
  hostname: process.env.DAO_RDP_HOST || "127.0.0.1",
  port: process.env.DAO_RDP_PORT || "13389",
  username: process.env.DAO_RDP_USER || "dao",
  password: process.env.DAO_RDP_PASS || "Dao@2026!",
};

const SESSIONS_JSON =
  process.env.DAO_SESSIONS_JSON || path.join(__dirname, "..", "sessions.json");

// 账号注册表（桥 core/accounts.py 建号时写入；隧道按账号铸造 token 时读取，同一真相源）。
const ACCOUNTS_JSON =
  process.env.DAO_ACCOUNTS_JSON || path.join(__dirname, "..", "accounts.json");

// 会话租约台账（窗口↔会话持久绑定）：每个 IDE 窗口/分身按其稳定 key（ide 或 ide.分身号）
// 首次取 token 即登记一条租约(lease)，落盘持久化；同一 key 复连（IDE 重启后）命中同一 leaseId，
// 从而确定性地复归“同一路桌面身份+同一账号/目标”。
//
// 诚实边界：RDP 协议本身无“连到指定 termsrv session id”的客户端参数，Windows 侧会话号由
// termsrv 分配（同账号多路 = 各自独立 Active）。故本租约持久化的是【窗口↔身份/账号/目标】的确定性
// 映射（复连回同一账号、同一 RDP 目标、同一逻辑桌面槽位），而非强制 termsrv 内部会话号。
const SESSIONS_STATE_JSON =
  process.env.DAO_SESSIONS_STATE_JSON ||
  path.join(__dirname, "..", "sessions-state.json");

function loadJson(p) {
  try {
    if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, "utf8")) || {};
  } catch (e) {
    console.error(`[tunnel] 解析 ${path.basename(p)} 失败:`, e.message);
  }
  return {};
}

// 账号 → RDP 目标。默认注册表恒含主账号 dao（即冷启动靶机）。
function accountsRegistry() {
  const reg = loadJson(ACCOUNTS_JSON);
  if (!reg[DEFAULT_RDP.username]) {
    reg[DEFAULT_RDP.username] = Object.assign({}, DEFAULT_RDP);
  }
  return reg;
}

function targetForAccount(account) {
  const reg = accountsRegistry();
  return reg[account] ? Object.assign({}, DEFAULT_RDP, reg[account]) : null;
}

// ide_<hash> → RDP 目标映射。缺省全部落到同一账号（rdpwrap 单账号多路 RDP：
// 每个 IDE 窗口一路独立会话，互不干扰）。可用 sessions.json 覆盖为不同靶机。
function targetForIde(ide) {
  const map = loadJson(SESSIONS_JSON);
  const t = (map && map[ide]) || {};
  return Object.assign({}, DEFAULT_RDP, t);
}

// —— 会话租约台账（窗口↔会话持久绑定）——
// key = 稳定的窗口/分身身份（ide 或 ide.分身号 或 account:分身号）。
function leaseKey(ide, account) {
  return account ? `account:${account}` : String(ide || "ide_default");
}

function loadLeases() {
  const st = loadJson(SESSIONS_STATE_JSON);
  return st && typeof st === "object" && st.leases ? st : { leases: {} };
}

function saveLeases(state) {
  try {
    const tmp = SESSIONS_STATE_JSON + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2));
    fs.renameSync(tmp, SESSIONS_STATE_JSON);
  } catch (e) {
    console.error("[tunnel] 落盘 sessions-state 失败:", e.message);
  }
}

// 登记/更新一条租约：首次见到该 key → 生成稳定 leaseId 并落盘；再次（含 IDE 重启后）
// 命中同一 key → 复用同一 leaseId + 复归同一账号/目标，实现窗口↔会话确定性复连。
function recordLease(ide, account, target) {
  const state = loadLeases();
  const key = leaseKey(ide, account);
  const now = new Date().toISOString();
  const prev = state.leases[key];
  const lease = prev || {
    leaseId: "lease_" + crypto.randomBytes(6).toString("hex"),
    key,
    firstSeen: now,
    mintCount: 0,
  };
  lease.ide = ide || null;
  lease.account = account || null;
  lease.target = target
    ? { hostname: target.hostname, port: String(target.port), username: target.username }
    : lease.target || null;
  lease.lastSeen = now;
  lease.mintCount = (lease.mintCount || 0) + 1;
  lease.reconnect = !!prev; // 本次是否为对既有租约的复连
  state.leases[key] = lease;
  saveLeases(state);
  return lease;
}

function listLeases() {
  const state = loadLeases();
  return Object.values(state.leases);
}

function dropLease(ide, account) {
  const state = loadLeases();
  const key = leaseKey(ide, account);
  const existed = !!state.leases[key];
  delete state.leases[key];
  saveLeases(state);
  return existed;
}

// 使用 guacamole-lite 的 Crypt 模块生成兼容 token（AES-256-CBC）。
const Crypt = require("guacamole-lite/lib/Crypt");
const crypt = new Crypt(CIPHER, KEY);
function encryptToken(payload) {
  return crypt.encrypt(payload);
}

// 为某 IDE 窗口 / 某账号铸造连接 token（RDP 明文凭据封进密文，浏览器只拿密文）。
// opts.account 优先（多账号类虚拟机·扩展本源）；否则按 ide_<hash> 映射（向后兼容）。
function mintToken(ide, opts) {
  opts = opts || {};
  const rdp = opts.account ? targetForAccount(opts.account) : targetForIde(ide);
  if (!rdp) throw new Error(`未知账号: ${opts.account}`);
  const settings = {
    hostname: rdp.hostname,
    port: String(rdp.port),
    username: rdp.username,
    password: rdp.password,
    security: rdp.security || "any", // NLA 关（firstlogon 已设），any 兼容
    "ignore-cert": "true",
    width: String((opts && opts.width) || 1280),
    height: String((opts && opts.height) || 800),
    dpi: String((opts && opts.dpi) || 96),
    "resize-method": "display-update",
  };
  if (rdp.domain) settings.domain = rdp.domain;
  return encryptToken({ connection: { type: "rdp", settings } });
}

// —— 令牌铸造 HTTP（供插件/网页取 token；不外泄加密密钥）——
const httpServer = http.createServer((req, res) => {
  const u = new URL(req.url, `http://127.0.0.1:${HTTP_PORT}`);
  res.setHeader("Access-Control-Allow-Origin", "*");
  if (u.pathname === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, ws_port: WS_PORT, guacd: `${GUACD_HOST}:${GUACD_PORT}` }));
    return;
  }
  if (u.pathname === "/accounts") {
    const reg = accountsRegistry();
    const accounts = Object.keys(reg).map((name) => ({
      name,
      hostname: reg[name].hostname,
      port: String(reg[name].port),
    }));
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, accounts }));
    return;
  }
  if (u.pathname === "/sessions") {
    // GET  /sessions            列全部租约
    // GET  /sessions?ide=X      查单条租约（含 reconnect 标志）
    // POST /sessions/drop?ide=X 释放一条租约（窗口关闭/分身销毁时调用）
    const ide = u.searchParams.get("ide") || undefined;
    const account = u.searchParams.get("account") || undefined;
    if (req.method === "POST") {
      const dropped = dropLease(ide, account);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, dropped }));
      return;
    }
    let out = listLeases();
    if (ide || account) {
      const key = leaseKey(ide, account);
      out = out.filter((l) => l.key === key);
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, leases: out }));
    return;
  }
  if (u.pathname === "/token") {
    const ide = u.searchParams.get("ide") || "ide_default";
    const account = u.searchParams.get("account") || undefined;
    const width = parseInt(u.searchParams.get("width") || "0", 10) || undefined;
    const height = parseInt(u.searchParams.get("height") || "0", 10) || undefined;
    const dpi = parseInt(u.searchParams.get("dpi") || "0", 10) || undefined;
    try {
      const token = mintToken(ide, { account, width, height, dpi });
      const target = account ? targetForAccount(account) : targetForIde(ide);
      const lease = recordLease(ide, account, target);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        token, ws_port: WS_PORT, ide, account: account || null,
        leaseId: lease.leaseId, reconnect: lease.reconnect,
      }));
    } catch (e) {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: String(e.message || e) }));
    }
    return;
  }
  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "not found" }));
});
// 仅当作为入口进程直接运行时才起监听/隧道；被 require（单测）时只暴露纯函数，不占端口、不连 guacd。
function startServer() {
httpServer.listen(HTTP_PORT, BIND, () => {
  console.log(`[tunnel] 令牌铸造 HTTP 就绪 http://${BIND}:${HTTP_PORT}/token?ide=<hash>`);
});

// —— guacamole-lite 隧道（浏览器 WS ↔ guacd）——
// 无效/缺失 token 的握手先在 upgrade 阶段拒掉：guacamole-lite 校验失败后仍会走
// ClientConnection.connect（读 undefined.connection 抛未捕获异常杀死进程），
// 等于任何未鉴权探测都能打死整条桌面路由链路。
const wsHttpServer = http.createServer();
wsHttpServer.prependListener("upgrade", (req, socket) => {
  let ok = false;
  try {
    const u = new URL(req.url, `http://127.0.0.1:${WS_PORT}`);
    const payload = crypt.decrypt(u.searchParams.get("token") || "");
    ok = !!(payload && payload.connection);
  } catch (e) {
    ok = false;
  }
  if (!ok) {
    console.error("[tunnel] 拒绝无效 token 握手（不中断服务）");
    socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
    socket.destroy();
  }
});
// 兜底：单连接异常不得杀死整个隧道进程。
process.on("uncaughtException", (err) => {
  console.error("[tunnel] 未捕获异常（已兜底，进程存活）:", err && err.message);
});
const guacServer = new GuacamoleLite(
  { server: wsHttpServer.listen(WS_PORT, BIND) },
  { host: GUACD_HOST, port: GUACD_PORT },
  {
    crypt: { cypher: CIPHER, key: KEY },
    log: { level: "NORMAL" },
    // 桌面会话本就可长时间无输入；guacamole-lite 默认 10s 无客户端消息即 1011 踢线（真机踩坑：面板每 10s 掉线重连循环）。
    maxInactivityTime: 0,
    connectionDefaultSettings: {
      rdp: { "ignore-cert": true, security: "any" },
    },
  }
);
guacServer.on("open", (conn) => console.log(`[tunnel] 会话打开 ${conn.connectionId || 'unknown'}`));
guacServer.on("close", (conn) => console.log(`[tunnel] 会话关闭 ${conn.connectionId || 'unknown'}`));
guacServer.on("error", (conn, err) => console.error("[tunnel] 错误:", err && err.message));
console.log(`[tunnel] WebSocket↔guacd 隧道就绪 ws://127.0.0.1:${WS_PORT}/?token=<token>  guacd=${GUACD_HOST}:${GUACD_PORT}`);
}

if (require.main === module) {
  startServer();
}

module.exports = {
  mintToken, encryptToken, startServer,
  leaseKey, recordLease, listLeases, dropLease, loadLeases,
  SESSIONS_STATE_JSON,
};
