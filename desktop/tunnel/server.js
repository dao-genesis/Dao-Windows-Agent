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
  if (u.pathname === "/token") {
    const ide = u.searchParams.get("ide") || "ide_default";
    const account = u.searchParams.get("account") || undefined;
    const width = parseInt(u.searchParams.get("width") || "0", 10) || undefined;
    const height = parseInt(u.searchParams.get("height") || "0", 10) || undefined;
    const dpi = parseInt(u.searchParams.get("dpi") || "0", 10) || undefined;
    try {
      const token = mintToken(ide, { account, width, height, dpi });
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ token, ws_port: WS_PORT, ide, account: account || null }));
    } catch (e) {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: String(e.message || e) }));
    }
    return;
  }
  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "not found" }));
});
httpServer.listen(HTTP_PORT, BIND, () => {
  console.log(`[tunnel] 令牌铸造 HTTP 就绪 http://${BIND}:${HTTP_PORT}/token?ide=<hash>`);
});

// —— guacamole-lite 隧道（浏览器 WS ↔ guacd）——
const guacServer = new GuacamoleLite(
  { server: http.createServer().listen(WS_PORT, BIND) },
  { host: GUACD_HOST, port: GUACD_PORT },
  {
    crypt: { cypher: CIPHER, key: KEY },
    log: { level: "NORMAL" },
    connectionDefaultSettings: {
      rdp: { "ignore-cert": true, security: "any" },
    },
  }
);
guacServer.on("open", (conn) => console.log(`[tunnel] 会话打开 ${conn.connectionId || 'unknown'}`));
guacServer.on("close", (conn) => console.log(`[tunnel] 会话关闭 ${conn.connectionId || 'unknown'}`));
guacServer.on("error", (conn, err) => console.error("[tunnel] 错误:", err && err.message));
console.log(`[tunnel] WebSocket↔guacd 隧道就绪 ws://127.0.0.1:${WS_PORT}/?token=<token>  guacd=${GUACD_HOST}:${GUACD_PORT}`);

module.exports = { mintToken, encryptToken };
