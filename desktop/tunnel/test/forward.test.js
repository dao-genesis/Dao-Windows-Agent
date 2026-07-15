// 后端换机转发对自检：agent(远端 WS→TCP) + connector(本地 TCP→WS) 字节回环、
// Bearer 鉴权拒绝、via 目标重写、同 via 连接子复用。全程回环网卡模拟穿透通道。
"use strict";
const assert = require("assert");
const net = require("net");

const fwd = require("../forward");

async function main() {
  // 0) 远端"RDP"替身：TCP echo 服务（只验字节透传，不解协议）。
  const echo = net.createServer((s) => s.pipe(s));
  await new Promise((r) => echo.listen(0, "127.0.0.1", r));
  const echoPort = echo.address().port;

  // 1) agent 起在"远端机"（回环模拟），带 Bearer 鉴权。
  const TOKEN = "dao-test-token";
  const agent = fwd.startAgent({ port: 0, token: TOKEN, targetPort: echoPort });
  await new Promise((r) => agent.once("listening", r));
  const agentPort = agent.address().port;
  const via = `ws://127.0.0.1:${agentPort}/rdp`;

  // 2) via 目标重写：hostname/port 重写为本地 connector 口，via/viaToken 不外泄。
  const target = {
    hostname: "ignored", port: "3389", username: "u", password: "p",
    via, viaToken: TOKEN,
  };
  const resolved = await fwd.resolveTarget(target);
  assert.strictEqual(resolved.hostname, "127.0.0.1");
  assert.ok(parseInt(resolved.port, 10) > 0, "应重写为本地 connector 口");
  assert.strictEqual(resolved.via, undefined, "via 不得残留在下发目标里");
  assert.strictEqual(resolved.viaToken, undefined, "viaToken 不得残留");
  assert.strictEqual(resolved.username, "u", "凭据字段原样保留");
  console.log("✓ via 目标重写为本地 connector 口 127.0.0.1:" + resolved.port);

  // 3) 同 via 复用同一 connector（多分身共用一口，不重复起监听）。
  const resolved2 = await fwd.resolveTarget({ via, viaToken: TOKEN });
  assert.strictEqual(resolved2.port, resolved.port, "同 via 应复用同一本地口");
  console.log("✓ 同 via 复用同一 connector 口");

  // 4) 字节回环：TCP → connector → WS → agent → TCP(echo) → 原路返回。
  const payload = Buffer.from("dao-rdp-bytes-\u9053\u6cd5\u81ea\u7136");
  const got = await new Promise((resolve, reject) => {
    const c = net.connect(parseInt(resolved.port, 10), "127.0.0.1", () => c.write(payload));
    const chunks = [];
    c.on("data", (b) => {
      chunks.push(b);
      if (Buffer.concat(chunks).length >= payload.length) {
        c.destroy();
        resolve(Buffer.concat(chunks));
      }
    });
    c.on("error", reject);
    setTimeout(() => reject(new Error("回环超时")), 5000);
  });
  assert.ok(got.equals(payload), "回环字节必须逐字相等");
  console.log("✓ 字节回环 TCP↔WS↔TCP 逐字相等 (" + payload.length + "B)");

  // 5) 鉴权：错 token 的 WS 握手必须被 agent 拒绝。
  const bad = await new Promise((resolve) => {
    const { WebSocket } = require("ws");
    const ws = new WebSocket(via, { headers: { Authorization: "Bearer wrong" } });
    ws.on("open", () => resolve("open"));
    ws.on("error", () => resolve("rejected"));
  });
  assert.strictEqual(bad, "rejected", "错误 token 必须被拒");
  console.log("✓ 错误 Bearer token 被 agent 拒绝");

  await fwd.closeConnectors();
  agent.close();
  echo.close();
  console.log("\nPASS desktop/tunnel/test/forward.test.js");
}

main().then(() => process.exit(0), (e) => { console.error(e); process.exit(1); });
