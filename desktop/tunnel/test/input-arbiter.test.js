// 输入并发协作层自检：不同分身互不阻塞；同分身短租约轮替；用户可抢占 Agent；
// 同级先到先得；TTL 过期自动释放；仅持有者可释放。注入假时钟，确定性。
"use strict";
const assert = require("assert");
const { InputArbiter, HUMAN, AGENT } = require("../input-arbiter");

let t = 1000;
const arb = new InputArbiter({ defaultTtlMs: 100, now: () => t });

// 1) 不同分身互不阻塞（你操作你的，我操作我的）。
const a1 = arb.acquire("account:dao#1", { id: "agentA", kind: AGENT });
const a2 = arb.acquire("account:dao#2", { id: "agentB", kind: AGENT });
assert.ok(a1.granted && a2.granted, "不同分身应各自独立授予");
assert.ok(arb.canInput("account:dao#1", "agentA"));
assert.ok(arb.canInput("account:dao#2", "agentB"));
console.log("✓ 不同分身各自独立输入权，互不阻塞");

// 2) 同分身：Agent 持有时，另一 Agent（同级）被拒（先到先得）。
const a1b = arb.acquire("account:dao#1", { id: "agentX", kind: AGENT });
assert.strictEqual(a1b.granted, false);
assert.strictEqual(a1b.holder.ownerId, "agentA");
assert.strictEqual(arb.canInput("account:dao#1", "agentX"), false, "非持有者不得注入");
console.log("✓ 同分身同级先到先得，后到者被拒且不得注入");

// 3) 用户(human)可抢占 Agent（用户随时接管/协助）。
const h1 = arb.acquire("account:dao#1", { id: "userU", kind: HUMAN });
assert.strictEqual(h1.granted, true, "用户应抢占 Agent");
assert.strictEqual(h1.preempted.ownerId, "agentA", "应报告被抢占者");
assert.strictEqual(arb.holder("account:dao#1").kind, HUMAN);
assert.strictEqual(arb.canInput("account:dao#1", "agentA"), false, "被抢占的 Agent 停手");
console.log("✓ 用户可抢占 Agent，被抢占方立即停手");

// 4) Agent 不能抢占用户（低优先级）。
const a1c = arb.acquire("account:dao#1", { id: "agentA", kind: AGENT });
assert.strictEqual(a1c.granted, false, "Agent 不得抢占用户");
console.log("✓ Agent 不得抢占用户");

// 5) TTL 过期自动释放 → Agent 可再取。
t += 101;
assert.strictEqual(arb.holder("account:dao#1"), null, "过期应自动释放");
const a1d = arb.acquire("account:dao#1", { id: "agentA", kind: AGENT });
assert.strictEqual(a1d.granted, true, "过期后 Agent 可再取");
console.log("✓ 租约 TTL 过期自动释放");

// 6) 仅持有者可释放；他人释放无效。
assert.strictEqual(arb.release("account:dao#1", "someoneElse"), false);
assert.strictEqual(arb.release("account:dao#1", "agentA"), true);
assert.strictEqual(arb.holder("account:dao#1"), null);
console.log("✓ 仅持有者可释放");

// 7) 持有者续租延长 TTL（同 id 再 acquire 保留 since、顺延过期）。
const s1 = arb.acquire("k", { id: "agentA", kind: AGENT });
t += 50;
const s2 = arb.acquire("k", { id: "agentA", kind: AGENT });
assert.strictEqual(s2.holder.since, s1.holder.since, "续租保留起始时刻");
assert.ok(s2.holder.expiresAt > s1.holder.expiresAt, "续租顺延过期");
console.log("✓ 持有者续租顺延 TTL、保留 since");

console.log("\nPASS desktop/tunnel/test/input-arbiter.test.js");
