/*
 * render_probe.js · rdp-web 渲染链路无头验证探针
 *
 * 道法自然 · 不新造体系：直接复用 gateway.js 的 RDP 摄取路径(node-rdpjs)，
 * 无头连接一路已激活的回环会话(127.0.0.x:port)，统计收到的 bitmap 帧，
 * 证明「RDP → 位图流」这条渲染链路在真机上真实产出帧；随后按需注入一次
 * 指针/键盘事件，验证输入通道可用。全程只连目标回环，不碰控制台。
 *
 * 用法:
 *   node render_probe.js --target 127.0.0.8 --port 3389 \
 *        --user ai --domain DESKTOP-MASTER --pass <PW> [--secs 8] [--inject]
 * 输出: 单行 JSON { ok, connected, frames, bytes, firstFrame, injected, error }
 */
const rdp = require('./rdpjs/lib');

function arg(name, def) {
    const i = process.argv.indexOf('--' + name);
    if (i >= 0) {
        const nxt = process.argv[i + 1];
        if (nxt === undefined || nxt.startsWith('--')) return true; // flag
        return nxt;
    }
    return def;
}

const target = arg('target', '127.0.0.2');
const port = Number(arg('port', 3389));
const user = arg('user', 'dao');
const domain = arg('domain', process.env.COMPUTERNAME || 'localhost');
const pass = arg('pass', '');
const secs = Number(arg('secs', 8));
const inject = arg('inject', false) === true;

let frames = 0;
let bytes = 0;
let connected = false;
let injected = false;
let firstFrame = 0;
let done = false;
const t0 = Date.now();

function finish(err) {
    if (done) return;
    done = true;
    try { client && client.close(); } catch (e) {}
    process.stdout.write(JSON.stringify({
        ok: connected && frames > 0,
        connected, frames, bytes,
        firstFrameMs: firstFrame ? firstFrame - t0 : 0,
        injected,
        target, port, user,
        error: err ? String((err && err.message) || err) : '',
    }) + '\n');
    setTimeout(() => process.exit(0), 100);
}

let client = rdp.createClient({
    domain: domain, userName: user, password: pass,
    enablePerf: true, autoLogin: true,
    screen: { width: 1024, height: 768 }, locale: 'en', logLevel: 'ERROR',
}).on('connect', () => {
    connected = true;
    if (inject) {
        // 目标会话内注入：移动+左键点击(桌面空白处)，再敲一次无害按键(scancode 0x39=空格)
        try {
            client.sendPointerEvent(120, 120, 1, true);
            client.sendPointerEvent(120, 120, 1, false);
            client.sendKeyEventScancode(0x39, true);
            client.sendKeyEventScancode(0x39, false);
            injected = true;
        } catch (e) {}
    }
}).on('bitmap', (b) => {
    frames++;
    bytes += (b && b.data && b.data.length) ? b.data.length : 0;
    if (!firstFrame) firstFrame = Date.now();
}).on('close', () => finish(null))
    .on('error', (err) => finish(err))
    .connect(target, port);

setTimeout(() => finish(null), secs * 1000);
