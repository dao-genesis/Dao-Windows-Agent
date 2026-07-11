#!/usr/bin/env node
// dao-mcp 纯逻辑自检: entry 构造 / 幂等合并 / disabled 保留 / 落盘注册。
"use strict";
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const m = require("../dao-mcp");

// entry 构造
const e = m.buildEntry({ pythonPath: "py3", runtimeDir: "/ext/runtime", bridgeUrl: "http://127.0.0.1:9920", token: "t" });
assert.deepStrictEqual(e.args, ["-m", "bridge.mcp"]);
assert.strictEqual(e.command, "py3");
assert.strictEqual(e.cwd, "/ext/runtime");
assert.strictEqual(e.env.DAO_WIN_BRIDGE_URL, "http://127.0.0.1:9920");
assert.strictEqual(e.env.DAO_WIN_TOKEN, "t");

// 空配置合并
let r = m.mergeMcpConfig("", e);
assert.strictEqual(r.changed, true);
assert.deepStrictEqual(r.cfg.mcpServers[m.SERVER_ID], e);

// 幂等: 再合并无变化
r = m.mergeMcpConfig(JSON.stringify(r.cfg), e);
assert.strictEqual(r.changed, false);

// 保留他人条目 + 本条目 disabled 状态
const prev = { mcpServers: { other: { command: "x" }, [m.SERVER_ID]: { command: "old", disabled: true } } };
r = m.mergeMcpConfig(JSON.stringify(prev), e);
assert.strictEqual(r.changed, true);
assert.deepStrictEqual(r.cfg.mcpServers.other, { command: "x" });
assert.strictEqual(r.cfg.mcpServers[m.SERVER_ID].disabled, true);
assert.strictEqual(r.cfg.mcpServers[m.SERVER_ID].command, "py3");

// 坏 JSON 容错
r = m.mergeMcpConfig("{oops", e);
assert.strictEqual(r.changed, true);

// 落盘注册(隔离 home)
const home = fs.mkdtempSync(path.join(os.tmpdir(), "daomcp-"));
const reg = m.registerDaoMcp({ home, pythonPath: "python", runtimeDir: "/rt" });
assert.strictEqual(reg.changed, true);
const onDisk = JSON.parse(fs.readFileSync(reg.path, "utf8"));
assert.strictEqual(onDisk.mcpServers[m.SERVER_ID].cwd, "/rt");
const reg2 = m.registerDaoMcp({ home, pythonPath: "python", runtimeDir: "/rt" });
assert.strictEqual(reg2.changed, false);
fs.rmSync(home, { recursive: true, force: true });

console.log("dao-mcp 自检通过");
