#!/usr/bin/env node
// ☯ 冷启动·经 CDP 取 IDE 登录用 auth code（show-auth-code 页·零 GUI）
//
// 前提：devin_inject_cdp.js 已把 app.devin.ai 登录态注入到带调试口的实例。
// 用法：node devin_fetch_code.js <out.txt> [cdpHost:port] [webapp]
//   在已登录 app.devin.ai 的 page 目标里开 show-auth-code 页，抓 auth code 落盘。
'use strict';
const http = require('http');
const { WS } = require('./devin_inject_cdp.js');

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

async function main() {
  const out = process.argv[2];
  const cdp = (process.argv[3] || '127.0.0.1:9222').split(':');
  const webapp = process.argv[4] || 'https://app.devin.ai';
  if (!out) { process.stderr.write('usage: devin_fetch_code.js <out.txt> [host:port] [webapp]\n'); process.exit(2); }

  const targets = await httpJson(cdp[0], cdp[1], '/json');
  const page = targets.find((t) => t.type === 'page' && /app\.devin\.ai/.test(t.url || '') && t.webSocketDebuggerUrl)
    || targets.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  if (!page) { process.stderr.write('无可用 page 目标\n'); process.exit(1); }

  const ws = new WS(page.webSocketDebuggerUrl);
  await ws.connect();
  let mid = 0; const pending = {};
  ws.onmsg = (raw) => { const m = JSON.parse(raw); if (m.id && pending[m.id]) { pending[m.id](m); delete pending[m.id]; } };
  const cmd = (method, params) => new Promise((res) => { const id = ++mid; pending[id] = res; ws.send(JSON.stringify({ id, method, params: params || {} })); });

  await cmd('Page.enable');
  await cmd('Runtime.enable');
  const prev = page.url;
  await cmd('Page.navigate', { url: webapp + '/auth/windsurf/show-auth-code?prompt=select_account&from=redirect' });

  let code = '';
  for (let i = 0; i < 20 && !code; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    const r = await cmd('Runtime.evaluate', {
      expression: "(function(){var t=document.body?document.body.innerText:'';" +
        "var m=t.match(/[A-Za-z0-9_-]{20,}/g)||[];" +
        "var el=document.querySelector('code,pre,[class*=code],[data-testid*=code]');" +
        "return JSON.stringify({sel:el?el.textContent.trim():'',cands:m.slice(0,8),url:location.href});})()",
      returnByValue: true });
    try {
      const v = JSON.parse(r.result.result.value);
      if (v.sel && /^[A-Za-z0-9_.-]{16,}$/.test(v.sel)) code = v.sel;
      else if (v.cands && v.cands.length === 1) code = v.cands[0];
      else if (v.cands && v.cands.length) {
        const c = v.cands.filter((x) => !/^https?/.test(x));
        if (c.length === 1) code = c[0];
      }
      if (i === 19 && !code) process.stderr.write('页面: ' + JSON.stringify(v) + '\n');
    } catch (e) { /* 页面未就绪，继续等 */ }
  }
  if (prev) await cmd('Page.navigate', { url: prev });
  if (!code) { process.stderr.write('未抓到 auth code\n'); ws.close(); process.exit(1); }
  require('fs').writeFileSync(out, code, { mode: 0o600 });
  process.stdout.write('code ok len=' + code.length + '\n');
  ws.close();
}

main().catch((e) => { process.stderr.write('ERR ' + (e && e.message || e) + '\n'); process.exit(1); });
