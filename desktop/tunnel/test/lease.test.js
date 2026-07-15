// 隧道会话租约台账自检（窗口↔会话持久绑定）：
// 首次取 token→登记租约(稳定 leaseId)；同 key 复连(IDE 重启)→命中同一 leaseId 且 reconnect=true；
// 不同分身 key→各自独立租约；drop→释放。require server.js 不得占端口/连 guacd。
"use strict";
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "dao-lease-"));
process.env.DAO_SESSIONS_STATE_JSON = path.join(tmp, "sessions-state.json");

const srv = require("../server");

// 0) require 不应起监听（纯函数导出）。
assert.strictEqual(typeof srv.recordLease, "function");
assert.strictEqual(typeof srv.mintToken, "function");
console.log("✓ require server.js 只暴露纯函数，不占端口");

// 1) 首次登记 → 生成稳定 leaseId，reconnect=false。
const t1 = srv.mintToken("ide_win1.1", {});
assert.ok(typeof t1 === "string" && t1.length > 0, "token 应为非空字符串");
const l1 = srv.recordLease("ide_win1.1", undefined, { hostname: "127.0.0.1", port: "13389", username: "dao" });
assert.ok(/^lease_[0-9a-f]{12}$/.test(l1.leaseId), "leaseId 格式");
console.log("✓ 首次取 token 登记稳定 lease: " + l1.leaseId);

// 2) 同 key 复连（模拟 IDE 重启后同 slot）→ 同一 leaseId 且 reconnect=true。
const l1b = srv.recordLease("ide_win1.1", undefined, { hostname: "127.0.0.1", port: "13389", username: "dao" });
assert.strictEqual(l1b.leaseId, l1.leaseId, "同 key 必须命中同一 leaseId（确定性复归）");
assert.strictEqual(l1b.reconnect, true, "第二次应标记 reconnect");
assert.strictEqual(l1b.mintCount, 2, "mintCount 应累加");
console.log("✓ 同 key 复连命中同一 lease，reconnect=true");

// 3) 不同分身 key → 各自独立租约。
const l2 = srv.recordLease("ide_win1.2", undefined, { hostname: "127.0.0.1", port: "13389", username: "dao" });
assert.notStrictEqual(l2.leaseId, l1.leaseId, "不同分身应各自独立 lease");
const all = srv.listLeases();
assert.strictEqual(all.length, 2, "应有两条独立租约, 实际=" + all.length);
console.log("✓ 不同分身各自独立租约, 共 " + all.length + " 条");

// 4) 账号路由 key 与 ide key 不冲突（account:<名> 独立命名空间）。
const la = srv.recordLease(null, "dao", { hostname: "127.0.0.1", port: "13389", username: "dao" });
assert.strictEqual(la.key, "account:dao");
assert.strictEqual(srv.listLeases().length, 3);
console.log("✓ 账号路由租约独立命名空间 account:dao");

// 4b) 单账号多分身：同账号不同 clone 号 → 各自独立租约；同 clone 复连命中同一 lease。
const lc1 = srv.recordLease(null, "dao", { hostname: "127.0.0.1", port: "13389", username: "dao" }, "1");
const lc2 = srv.recordLease(null, "dao", { hostname: "127.0.0.1", port: "13389", username: "dao" }, "2");
assert.strictEqual(lc1.key, "account:dao#1");
assert.strictEqual(lc2.key, "account:dao#2");
assert.notStrictEqual(lc1.leaseId, lc2.leaseId, "同账号不同分身应各自独立 lease");
assert.notStrictEqual(lc1.leaseId, la.leaseId, "分身租约不得与账号裸租约混同");
const lc1b = srv.recordLease(null, "dao", { hostname: "127.0.0.1", port: "13389", username: "dao" }, "1");
assert.strictEqual(lc1b.leaseId, lc1.leaseId, "同分身复连命中同一 leaseId");
assert.strictEqual(lc1b.reconnect, true);
assert.strictEqual(srv.listLeases().length, 5);
console.log("✓ 单账号多分身各自独立租约 account:dao#1 / account:dao#2");
assert.strictEqual(srv.dropLease(null, "dao", "2"), true);
assert.strictEqual(srv.listLeases().length, 4, "drop 分身只释放该分身");
console.log("✓ drop 指定分身不波及其它分身");

// 5) 落盘持久化：另起进程重新读取应保留（模拟隧道重启后台账仍在）。
const disk = JSON.parse(fs.readFileSync(process.env.DAO_SESSIONS_STATE_JSON, "utf8"));
assert.ok(disk.leases["ide_win1.1"] && disk.leases["ide_win1.1"].leaseId === l1.leaseId, "租约应落盘");
console.log("✓ 租约落盘持久化");

// 6) drop → 释放。
assert.strictEqual(srv.dropLease("ide_win1.1", undefined), true);
assert.strictEqual(srv.dropLease("ide_win1.1", undefined), false, "重复 drop 返回 false");
assert.strictEqual(srv.listLeases().length, 3, "drop 后应剩三条");
console.log("✓ drop 释放租约");

console.log("\nPASS desktop/tunnel/test/lease.test.js");
