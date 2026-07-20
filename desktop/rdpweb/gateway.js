/*
 * daordp gateway — 官方 RDP 协议反向路由进归一单网页(Windows 原生·零 Docker)。
 * 反者道之动:不自造交互,直接把官方终端服务(3389)的桌面本体经 node-rdpjs 协议客户端
 * 搬进浏览器 canvas;鼠键/滚轮/剪贴板走官方 RDP 输入 PDU,原生拖拽所见即所得。
 *
 * 主账号分身:同一 zhouyoukang 凭据连多路 loopback 别名(127.0.0.1/.2/…),
 * fSingleSessionPerUser=0 下每次登录=该账号一路独立会话,共享同一份软件/数据/资源。
 */
const http = require('http'), fs = require('fs'), path = require('path');
const { WebSocketServer } = require('ws');
const rdp = require('node-rdpjs-2');

const DIR = __dirname;
const CLIENT = path.join(DIR, 'client');
const PORT = parseInt(process.env.DAORDP_PORT || '9250', 10);

let CRED = { username: '', password: '', domain: '' };
try { CRED = JSON.parse(fs.readFileSync('C:/ProgramData/dao_vm/rdp_cred.json', 'utf8')); }
catch (e) { console.error('no rdp_cred.json:', e.message); }

// 主账号分身:同凭据 → 不同 loopback 别名 → 各自独立 zhouyoukang 会话
const TARGETS = {
  main1: { ip: '127.0.0.1', port: 3389 },
  main2: { ip: '127.0.0.2', port: 3389 }
};

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript',
  '.css': 'text/css', '.svg': 'image/svg+xml', '.ico': 'image/x-icon' };

const server = http.createServer((req, res) => {
  let p = req.url.split('?')[0];
  if (p === '/' || p === '/index.html') p = '/grid.html';
  const f = path.join(CLIENT, path.normalize(p).replace(/^([/\\])+/, ''));
  if (!f.startsWith(CLIENT)) { res.writeHead(403); res.end('no'); return; }
  fs.readFile(f, (err, data) => {
    if (err) { res.writeHead(404); res.end('nf'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream',
      'Cache-Control': 'no-store' });
    res.end(data);
  });
});

const wss = new WebSocketServer({ server, path: '/ws' });
wss.on('connection', (ws) => {
  let c = null;
  const send = (o) => { try { if (ws.readyState === 1) ws.send(JSON.stringify(o)); } catch (e) {} };
  ws.on('message', (raw) => {
    let m; try { m = JSON.parse(raw); } catch (e) { return; }
    if (m.t === 'infos') {
      if (c) { try { c.close(); } catch (e) {} c = null; }
      const tgt = TARGETS[m.target] || { ip: m.ip || '127.0.0.1', port: m.port || 3389 };
      try {
        c = rdp.createClient({
          domain: CRED.domain || '', userName: CRED.username, password: CRED.password,
          enablePerf: true, autoLogin: true, screen: m.screen || { width: 1280, height: 800 },
          locale: m.locale || 'en', logLevel: 'ERROR'
        }).on('connect', () => send({ t: 'connect' }))
          .on('bitmap', (b) => send({ t: 'bitmap', destTop: b.destTop, destLeft: b.destLeft,
            destRight: b.destRight, destBottom: b.destBottom, width: b.width, height: b.height,
            bitsPerPixel: b.bitsPerPixel, isCompress: b.isCompress, data: b.data.toString('base64') }))
          .on('close', () => send({ t: 'close' }))
          .on('error', (e) => send({ t: 'error', message: String((e && e.message) || e) }))
          .connect(tgt.ip, tgt.port);
      } catch (e) { send({ t: 'error', message: 'createClient: ' + e.message }); }
    } else if (m.t === 'mouse') { if (c) try { c.sendPointerEvent(m.x, m.y, m.button, m.isPressed); } catch (e) {} }
    else if (m.t === 'wheel') { if (c) try { c.sendWheelEvent(m.x, m.y, m.step, m.isNegative, m.isHorizontal); } catch (e) {} }
    else if (m.t === 'scancode') { if (c) try { c.sendKeyEventScancode(m.code, m.isPressed); } catch (e) {} }
    else if (m.t === 'unicode') { if (c) try { c.sendKeyEventUnicode(m.code, m.isPressed); } catch (e) {} }
  });
  ws.on('close', () => { if (c) try { c.close(); } catch (e) {} });
});

server.listen(PORT, '127.0.0.1', () => console.log('daordp gateway on 127.0.0.1:' + PORT));
