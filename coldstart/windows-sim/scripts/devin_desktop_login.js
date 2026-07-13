#!/usr/bin/env node
// ☯ 冷启动·Devin Desktop 原生登录闭环（零 GUI·零竞速）
//
// 思路：show-auth-code 的 code 仅绑定 app.devin.ai 已登录用户会话·单次·60s。GUI 手输太慢会过期，
//   故全程 CDP：① 独立 user-data-dir 的「铸造实例」注入 auth1 → 已登录 app.devin.ai；
//   ② 于铸造实例导航 show-auth-code 抓 code；③ 立即在「编辑器实例」登录页 CDP 填入 code 并提交。
//   铸造→填入同进程内毫秒级完成，稳过 60s 窗口，且落 Devin Desktop 原生持久登录态。
//
// 用法：node devin_desktop_login.js <auth.json> <editorCdp> <minterCdp> [webapp]
'use strict';
const http = require('http');
const { WS } = require('./devin_inject_cdp.js');

function hj(host, port, path) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host, port, path, method: 'GET', timeout: 8000 }, (res) => {
      const c = []; res.on('data', (d) => c.push(d));
      res.on('end', () => { try { resolve(JSON.parse(Buffer.concat(c).toString())); } catch (e) { reject(e); } });
    });
    req.on('error', reject); req.on('timeout', () => req.destroy(new Error('cdp http timeout'))); req.end();
  });
}

async function attach(hostport, match) {
  const [h, p] = hostport.split(':');
  const ts = await hj(h, p, '/json');
  const pg = (match && ts.find((t) => t.type === 'page' && match.test(t.url || '') && t.webSocketDebuggerUrl))
    || ts.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  const ws = new WS(pg.webSocketDebuggerUrl); await ws.connect();
  let mid = 0; const pend = {};
  ws.onmsg = (raw) => { const m = JSON.parse(raw); if (m.id && pend[m.id]) { pend[m.id](m); delete pend[m.id]; } };
  const cmd = (me, pa) => new Promise((r) => { const id = ++mid; pend[id] = r; ws.send(JSON.stringify({ id, method: me, params: pa || {} })); });
  await cmd('Page.enable'); await cmd('Runtime.enable');
  return { ws, cmd, url: pg.url };
}
const val = (r) => r && r.result && r.result.result && r.result.result.value;

async function main() {
  const authPath = process.argv[2];
  const editorCdp = process.argv[3] || '127.0.0.1:9333';
  const minterCdp = process.argv[4] || '127.0.0.1:9444';
  const webapp = process.argv[5] || 'https://app.devin.ai';
  const auth = JSON.parse(require('fs').readFileSync(authPath, 'utf8'));
  const A1 = auth.auth1, UID = auth.userId || '', ORG = auth.orgId || '', ORGN = auth.orgName || '';
  const J = JSON.stringify;

  // ① 铸造实例：注入登录态
  const m = await attach(minterCdp);
  await m.cmd('Page.navigate', { url: webapp + '/login' });
  await new Promise((r) => setTimeout(r, 4000));
  const inject =
    '(function(){try{' +
    "localStorage.setItem('auth1_session',JSON.stringify({token:" + J(A1) + ",userId:" + J(UID) + "}));" +
    "localStorage.setItem('migrated-to-unscoped-auth0-token-2025-12-18','true');" +
    (UID ? "localStorage.setItem('known-org-ids-'+" + J(UID) + ",JSON.stringify([" + J(ORG) + "]));" : '') +
    "localStorage.setItem('last-internal-org-for-external-org-v1-null'," + J(ORG) + ");" +
    "document.cookie='webapp_logged_in=true; path=/; max-age=31536000; SameSite=Lax';" +
    "return 'ok';}catch(e){return String(e);}})()";
  const ir = await m.cmd('Runtime.evaluate', { expression: inject, returnByValue: true });
  if (val(ir) !== 'ok') { process.stderr.write('铸造实例注入失败: ' + val(ir) + '\n'); process.exit(1); }

  // ② 抓 code（立即·单次）
  await m.cmd('Page.navigate', { url: webapp + '/auth/windsurf/show-auth-code?prompt=select_account&from=redirect' });
  let code = '';
  for (let i = 0; i < 15 && !code; i++) {
    await new Promise((r) => setTimeout(r, 1200));
    const r = await m.cmd('Runtime.evaluate', {
      expression: "(function(){var t=document.body?document.body.innerText:'';var m=t.match(/([A-Za-z0-9_-]{16,})\\s*\\n\\s*Copy token/);return m?m[1]:'';})()",
      returnByValue: true });
    if (val(r)) code = val(r);
  }
  if (!code) { process.stderr.write('未抓到 code\n'); process.exit(1); }

  // ③ 编辑器实例登录页：填 code 并提交（毫秒级·稳过 60s）
  const e = await attach(editorCdp, /show-auth-code|windsurf|app\.devin\.ai|welcome/i);
  const fill =
    '(function(){try{' +
    "var inp=document.querySelector('input[type=text],input:not([type]),input[placeholder*=oken],input[placeholder*=Token]');" +
    "if(!inp)return 'no-input';" +
    "var set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;" +
    "set.call(inp," + J(code) + ");" +
    "inp.dispatchEvent(new Event('input',{bubbles:true}));" +
    "inp.dispatchEvent(new Event('change',{bubbles:true}));" +
    "return 'filled';}catch(e){return String(e);}})()";
  const fr = await e.cmd('Runtime.evaluate', { expression: fill, returnByValue: true });
  if (val(fr) !== 'filled') { process.stderr.write('填入失败: ' + val(fr) + '\n'); process.exit(1); }
  await new Promise((r) => setTimeout(r, 300));
  const click =
    '(function(){var b=[].slice.call(document.querySelectorAll(\'button\')).find(function(x){return /log ?in/i.test(x.textContent||\'\');});if(b){b.click();return \'clicked\';}return \'no-btn\';})()';
  const cr = await e.cmd('Runtime.evaluate', { expression: click, returnByValue: true });
  process.stdout.write('submit → ' + val(cr) + ' (code len=' + code.length + ')\n');
  await new Promise((r) => setTimeout(r, 6000));
  const chk = await e.cmd('Runtime.evaluate', { expression: "JSON.stringify({url:location.href,body:(document.body?document.body.innerText:'').slice(0,120)})", returnByValue: true });
  process.stdout.write('after → ' + val(chk) + '\n');
  m.ws.close(); e.ws.close();
}
main().catch((err) => { process.stderr.write('ERR ' + (err && err.message || err) + '\n'); process.exit(1); });
