#!/usr/bin/env node
// ☯ 冷启动·CDP 登录态注入（配合 devin_auth.js·彻底规避 GUI）
//
// 道法自然：Chrome/Edge 与 Devin Desktop(Electron) 皆开放 CDP(远程调试端口)。本模块以零依赖
//   内建 WebSocket 客户端连 CDP，于 app.devin.ai 真源同源注入 auth1_session(键 1:1 对齐 rt-flow)
//   → 刷新后 SPA 自判已登录 → 落 /org/<orgName>。全程无一次键鼠 GUI。
//
// 用法：node devin_inject_cdp.js <auth.json> [cdpHost:port] [webapp]
//   auth.json  : devin_auth.js bundle 产出的 auth 束（含 auth1/userId/orgId；不含密码）
//   cdpHost    : 默认 127.0.0.1:9222（guest 内 Devin Desktop/浏览器远程调试口）
//   webapp     : 默认 https://app.devin.ai
//
// 安全：只消费 auth 束（短时 bearer），不接触明文密码；不写任何日志敏感项。

'use strict';
const http = require('http');
const net = require('net');
const crypto = require('crypto');

function httpJson(host, port, path) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host, port, path, method: 'GET', timeout: 8000 }, (res) => {
      const c = [];
      res.on('data', (d) => c.push(d));
      res.on('end', () => { try { resolve(JSON.parse(Buffer.concat(c).toString('utf8'))); } catch (e) { reject(e); } });
    });
    req.on('error', reject);
    req.on('timeout', () => req.destroy(new Error('cdp http timeout')));
    req.end();
  });
}

// 极简 CDP WebSocket 客户端（RFC6455 客户端帧·掩码）——零外部依赖。
class WS {
  constructor(url) {
    const u = new URL(url);
    this.host = u.hostname;
    this.port = u.port || 80;
    this.path = u.pathname + u.search;
    this.buf = Buffer.alloc(0);
    this.onmsg = null;
  }
  connect() {
    return new Promise((resolve, reject) => {
      const key = crypto.randomBytes(16).toString('base64');
      this.sock = net.connect(this.port, this.host, () => {
        this.sock.write(
          'GET ' + this.path + ' HTTP/1.1\r\n' +
          'Host: ' + this.host + ':' + this.port + '\r\n' +
          'Upgrade: websocket\r\nConnection: Upgrade\r\n' +
          'Sec-WebSocket-Key: ' + key + '\r\nSec-WebSocket-Version: 13\r\n\r\n');
      });
      let handshook = false;
      this.sock.on('data', (d) => {
        if (!handshook) {
          this.buf = Buffer.concat([this.buf, d]);
          const idx = this.buf.indexOf('\r\n\r\n');
          if (idx === -1) return;
          handshook = true;
          const rest = this.buf.slice(idx + 4);
          this.buf = Buffer.alloc(0);
          resolve();
          if (rest.length) this._feed(rest);
        } else {
          this._feed(d);
        }
      });
      this.sock.on('error', reject);
      this.sock.on('timeout', () => this.sock.destroy(new Error('ws timeout')));
      this.sock.setTimeout(15000);
    });
  }
  _feed(d) {
    this.buf = Buffer.concat([this.buf, d]);
    while (this.buf.length >= 2) {
      const b1 = this.buf[1];
      let len = b1 & 0x7f;
      let off = 2;
      if (len === 126) { if (this.buf.length < 4) return; len = this.buf.readUInt16BE(2); off = 4; }
      else if (len === 127) { if (this.buf.length < 10) return; len = Number(this.buf.readBigUInt64BE(2)); off = 10; }
      if (this.buf.length < off + len) return;
      const payload = this.buf.slice(off, off + len).toString('utf8');
      this.buf = this.buf.slice(off + len);
      if (this.onmsg) this.onmsg(payload);
    }
  }
  send(str) {
    const payload = Buffer.from(str, 'utf8');
    const len = payload.length;
    const mask = crypto.randomBytes(4);
    let header;
    if (len < 126) header = Buffer.from([0x81, 0x80 | len]);
    else if (len < 65536) { header = Buffer.alloc(4); header[0] = 0x81; header[1] = 0x80 | 126; header.writeUInt16BE(len, 2); }
    else { header = Buffer.alloc(10); header[0] = 0x81; header[1] = 0x80 | 127; header.writeBigUInt64BE(BigInt(len), 2); }
    const masked = Buffer.alloc(len);
    for (let i = 0; i < len; i++) masked[i] = payload[i] ^ mask[i & 3];
    this.sock.write(Buffer.concat([header, mask, masked]));
  }
  close() { try { this.sock.destroy(); } catch (e) {} }
}

async function main() {
  const authPath = process.argv[2];
  const cdp = (process.argv[3] || '127.0.0.1:9222').split(':');
  const webapp = process.argv[4] || 'https://app.devin.ai';
  if (!authPath) { process.stderr.write('usage: devin_inject_cdp.js <auth.json> [host:port] [webapp]\n'); process.exit(2); }
  const auth = JSON.parse(require('fs').readFileSync(authPath, 'utf8'));
  const A1 = auth.auth1, UID = auth.userId || '', ORG = auth.orgId || '', ORGN = auth.orgName || '';
  if (!A1 || !ORG) { process.stderr.write('auth bundle 缺 auth1/orgId\n'); process.exit(1); }

  const targets = await httpJson(cdp[0], cdp[1], '/json');
  const page = targets.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  if (!page) { process.stderr.write('无可用 page 目标（确认已带远程调试口启动）\n'); process.exit(1); }

  const ws = new WS(page.webSocketDebuggerUrl);
  await ws.connect();
  let mid = 0;
  const pending = {};
  ws.onmsg = (raw) => { const m = JSON.parse(raw); if (m.id && pending[m.id]) { pending[m.id](m); delete pending[m.id]; } };
  const cmd = (method, params) => new Promise((res) => { const id = ++mid; pending[id] = res; ws.send(JSON.stringify({ id, method, params: params || {} })); });

  await cmd('Page.enable');
  await cmd('Runtime.enable');
  await cmd('Page.navigate', { url: webapp + '/login' });
  await new Promise((r) => setTimeout(r, 4000));
  const J = JSON.stringify;
  const inject =
    '(function(){try{' +
    "localStorage.setItem('auth1_session',JSON.stringify({token:" + J(A1) + ",userId:" + J(UID) + "}));" +
    "localStorage.setItem('migrated-to-unscoped-auth0-token-2025-12-18','true');" +
    (UID ? "localStorage.setItem('known-org-ids-'+" + J(UID) + ",JSON.stringify([" + J(ORG) + "]));" : '') +
    "localStorage.setItem('last-internal-org-for-external-org-v1-null'," + J(ORG) + ");" +
    (UID && ORGN ? "var __k='post-auth-v3-null-'+" + J(UID) + "+'-org_name-'+" + J(ORGN) + ";if(!localStorage.getItem(__k))localStorage.setItem(__k,JSON.stringify({externalOrgId:null,userId:" + J(UID) + ",internalOrgId:" + J(ORG) + ",orgName:" + J(ORGN) + ",result:{resolved_external_org_id:null,org_id:" + J(ORG) + ",org_name:" + J(ORGN) + ",is_valid_resource:true}}));" : '') +
    "document.cookie='webapp_logged_in=true; path=/; max-age=31536000; SameSite=Lax';" +
    "return 'ok';}catch(e){return String(e);}})()";
  const r = await cmd('Runtime.evaluate', { expression: inject, returnByValue: true });
  const iv = r.result && r.result.result && r.result.result.value;
  if (iv !== 'ok') { process.stderr.write('注入失败: ' + iv + '\n'); ws.close(); process.exit(1); }
  await cmd('Page.navigate', { url: webapp + '/' });
  await new Promise((r) => setTimeout(r, 5000));
  const chk = await cmd('Runtime.evaluate', { expression: 'JSON.stringify({url:location.href,hasAuth:!!localStorage.getItem("auth1_session")})', returnByValue: true });
  process.stdout.write('inject ok → ' + (chk.result && chk.result.result && chk.result.result.value) + '\n');
  ws.close();
}

if (require.main === module) main().catch((e) => { process.stderr.write('ERR ' + (e && e.message || e) + '\n'); process.exit(1); });
module.exports = { WS };
