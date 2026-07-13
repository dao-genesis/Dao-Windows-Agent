#!/usr/bin/env node
// ☯ 冷启动·经 CDP 驱动 Devin Desktop workbench UI（绕开 guacd RDP 键位限制）
//   guacd 隧道只稳传组合键(Ctrl+Shift+P)不稳传字符，故用 CDP Input.insertText 直投 renderer。
// 用法：node cdp_ui.js <cdpHost:port> <op> [arg]
//   ops: palette <text>        打开命令面板并填入过滤词
//        insert <text>          向当前焦点插入文本
//        enter                  回车
//        esc                    Esc
//        eval <js>              renderer 求值并打印
//        quickpick              打印当前 quick-pick 可见项
'use strict';
const http = require('http');
const { WS } = require('./devin_inject_cdp.js');
function hj(h, p, path) {
  return new Promise((res, rej) => {
    const q = http.request({ host: h, port: p, path, method: 'GET', timeout: 8000 }, (r) => {
      const c = []; r.on('data', (d) => c.push(d)); r.on('end', () => { try { res(JSON.parse(Buffer.concat(c).toString())); } catch (e) { rej(e); } });
    }); q.on('error', rej); q.end();
  });
}
async function main() {
  const [h, p] = (process.argv[2] || '127.0.0.1:9333').split(':');
  const op = process.argv[3]; const arg = process.argv[4] || '';
  const ts = await hj(h, p, '/json');
  const pg = ts.find((t) => t.type === 'page' && /workbench\.html/.test(t.url || '') && t.webSocketDebuggerUrl)
    || ts.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  const ws = new WS(pg.webSocketDebuggerUrl); await ws.connect();
  let mid = 0; const pend = {};
  ws.onmsg = (raw) => { const m = JSON.parse(raw); if (m.id && pend[m.id]) { pend[m.id](m); delete pend[m.id]; } };
  const cmd = (me, pa) => new Promise((r) => { const id = ++mid; pend[id] = r; ws.send(JSON.stringify({ id, method: me, params: pa || {} })); });
  await cmd('Runtime.enable'); await cmd('Input.enable').catch(() => {});
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const key = async (k, vk) => {
    await cmd('Input.dispatchKeyEvent', { type: 'keyDown', key: k, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
    await cmd('Input.dispatchKeyEvent', { type: 'keyUp', key: k, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
  };
  const listQuick = async () => {
    const r = await cmd('Runtime.evaluate', { expression:
      "(function(){var rows=[].slice.call(document.querySelectorAll('.quick-input-list .monaco-list-row'));return JSON.stringify(rows.slice(0,12).map(function(x){return (x.innerText||'').replace(/\\s+/g,' ').trim();}));})()",
      returnByValue: true });
    return r.result && r.result.result && r.result.result.value;
  };
  if (op === 'palette') {
    await key('P', 80); // 兜底：若已开则无碍
    await sleep(400);
    // 确保命令面板打开（VS Code: quickOpen with '>')
    await cmd('Runtime.evaluate', { expression: "document.activeElement && document.activeElement.tagName", returnByValue: true });
    await cmd('Input.insertText', { text: arg });
    await sleep(800);
    process.stdout.write('quick=' + (await listQuick()) + '\n');
  } else if (op === 'insert') {
    await cmd('Input.insertText', { text: arg }); await sleep(600);
    process.stdout.write('quick=' + (await listQuick()) + '\n');
  } else if (op === 'enter') {
    await key('Enter', 13); await sleep(1200);
    process.stdout.write('quick=' + (await listQuick()) + '\n');
  } else if (op === 'down') {
    const n = parseInt(arg || '1', 10);
    for (let i = 0; i < n; i++) { await key('ArrowDown', 40); await sleep(150); }
    process.stdout.write('quick=' + (await listQuick()) + '\n');
  } else if (op === 'downenter') {
    const n = parseInt(arg || '1', 10);
    for (let i = 0; i < n; i++) { await key('ArrowDown', 40); await sleep(150); }
    await sleep(200); await key('Enter', 13); await sleep(1400);
    process.stdout.write('quick=' + (await listQuick()) + '\n');
  } else if (op === 'pick') {
    // 选 index=arg(0基) 项并接受；接受后 renderer 可能重绘，故不回读、直接强退
    const n = parseInt(arg || '0', 10);
    for (let i = 0; i < n; i++) { await key('ArrowDown', 40); await sleep(150); }
    await sleep(200); await key('Enter', 13); await sleep(1200);
    process.stdout.write('picked idx=' + n + '\n');
    try { ws.close(); } catch (e) {}
    process.exit(0);
  } else if (op === 'esc') {
    await key('Escape', 27); await sleep(300);
  } else if (op === 'quickpick') {
    process.stdout.write('quick=' + (await listQuick()) + '\n');
  } else if (op === 'eval') {
    const r = await cmd('Runtime.evaluate', { expression: arg, returnByValue: true });
    process.stdout.write('eval=' + JSON.stringify(r.result && r.result.result && r.result.result.value) + '\n');
  }
  ws.close();
}
main().catch((e) => { process.stderr.write('ERR ' + (e && e.message || e) + '\n'); process.exit(1); });
