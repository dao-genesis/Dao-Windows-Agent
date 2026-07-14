// host-state 自检: publishFused 不动点 + hostFire 重入护栏 —— 防「监听→发布→广播」自激循环。
"use strict";
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "dao-hs-"));
process.env.DAO_WINDSURF_HOST_FILE = path.join(tmp, "windsurf-host.json");
delete globalThis.__daoWindsurfHost;

const hs = require("../dao-ai-base/dao-cascade/host-state");

// 1) 相同载荷重复发布: 不广播、返回原对象(不动点)。
{
  let fires = 0;
  const sub = hs.subscribe(() => { fires++; });
  const a = hs.publishFused("engines", { cascade: { ready: true }, n: 1 });
  const b = hs.publishFused("engines", { cascade: { ready: true }, n: 1 });
  assert.strictEqual(a, b, "相同载荷应返回同一对象");
  assert.strictEqual(fires, 1, "相同载荷不应再次广播, fires=" + fires);
  const c = hs.publishFused("engines", { cascade: { ready: false }, n: 2 });
  assert.notStrictEqual(b, c, "载荷变化应产生新对象");
  assert.strictEqual(fires, 2, "载荷变化应广播一次");
  sub.dispose();
  console.log("✓ publishFused 不动点(去时间戳比较)");
}

// 2) 监听回调内再发布(曾致死循环): 同步不递归、有限次收敛。
{
  let calls = 0;
  const sub = hs.subscribe(() => {
    calls++;
    assert.ok(calls < 50, "监听→发布自激未收敛");
    // 曾经的病灶: 回调内 publishFused 相同载荷 → hostFire → 回调 → 无限循环
    hs.publishFused("loopProbe", { same: true });
  });
  hs.publishFused("loopTrigger", { go: 1 });
  assert.ok(calls <= 3, "应快速收敛, calls=" + calls);
  sub.dispose();
  console.log("✓ hostFire 重入护栏(回调内发布不自激, calls=" + calls + ")");
}

// 3) 载荷持续变化时也不同步爆栈: _firing 期间只标记待发。
{
  let calls = 0;
  const sub = hs.subscribe(() => {
    calls++;
    if (calls < 5) hs.publishFused("mut", { v: calls });
  });
  hs.publishFused("mut", { v: -1 });
  assert.ok(calls <= 6, "变载荷也应受重入护栏约束, calls=" + calls);
  sub.dispose();
  console.log("✓ 变载荷回调发布不同步爆栈(calls=" + calls + ")");
}

console.log("host-state 自检通过 ✓");
