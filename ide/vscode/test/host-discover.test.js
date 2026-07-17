#!/usr/bin/env node
// host-discover / ls-bridge 自检: 发现轮询不得每拍做重活(实机曾致扩展宿主无响应)。
//   ① apiKeyCandidates TTL 缓存 —— 30s 内重复调用不再重读磁盘(state.vscdb 可达数十 MB);
//   ② invalidateKeyCache 强制刷新;
//   ③ win32 短路 —— lsPids/listenPortsOf 不 spawn 必败 shell(无 pgrep/lsof);
//   ④ 先廉后贵 —— 无可探 LS 目标时 discover() 不读 apiKey 候选(不碰磁盘重活)。
"use strict";
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "dao-hd-"));
const credFile = path.join(tmp, "credentials.toml");
fs.writeFileSync(credFile, 'windsurf_api_key = "key-one"\n');
process.env.DAO_DEVIN_CRED_FILE = credFile;
process.env.DAO_WINDSURF_HOST_FILE = path.join(tmp, "windsurf-host.json");

// 密闭化: state.vscdb 候选按 homedir 派生默认安装路径 —— 指向空 tmp,
// 避免测试机真实 IDE 登录态(%APPDATA%/Devin 等)漏入候选集污染断言。
const realHomedir = os.homedir;
os.homedir = () => tmp;
const realAppData = process.env.APPDATA;
process.env.APPDATA = path.join(tmp, "AppData", "Roaming");

// 计数指定文件的同步读(其余透传)。
let credReads = 0;
const realRead = fs.readFileSync;
fs.readFileSync = function (p, ...rest) {
  if (p === credFile) credReads++;
  return realRead.call(fs, p, ...rest);
};

const ls = require("../dao-ai-base/dao-cascade/ls-bridge");
const hd = require("../dao-ai-base/dao-cascade/host-discover");

// ① TTL 缓存: 第二次调用不再读盘, 且结果一致。
ls.invalidateKeyCache();
const k1 = ls.apiKeyCandidates();
assert.deepStrictEqual(k1, ["key-one"]);
const readsAfterFirst = credReads;
assert.ok(readsAfterFirst >= 1, "首次应读盘");
const k2 = ls.apiKeyCandidates();
assert.deepStrictEqual(k2, ["key-one"]);
assert.strictEqual(credReads, readsAfterFirst, "TTL 内重复调用不得重读磁盘");
// 缓存返回副本, 调用方改写不污染缓存。
k2.push("mutated");
assert.deepStrictEqual(ls.apiKeyCandidates(), ["key-one"]);

// ② invalidateKeyCache 强制刷新: 换 key 后可见新值。
fs.writeFileSync(credFile, 'windsurf_api_key = "key-two"\n');
ls.invalidateKeyCache();
assert.deepStrictEqual(ls.apiKeyCandidates(), ["key-two"]);
assert.ok(credReads > readsAfterFirst, "失效后应重读磁盘");

// ③ win32 短路: 不得 spawn 任何子进程(pgrep/lsof 在 Windows 不存在)。
const realPlatform = Object.getOwnPropertyDescriptor(process, "platform");
const realExecSync = cp.execSync;
cp.execSync = () => { throw new Error("win32 路径不得 spawn shell"); };
Object.defineProperty(process, "platform", { value: "win32" });
try {
  assert.deepStrictEqual(hd.lsPids(), []);
  assert.deepStrictEqual(hd.listenPortsOf(12345), []);

  // ④ 先廉后贵: 无目标 → discover() 返回 null 且不读 apiKey 候选。
  ls.invalidateKeyCache();
  const before = credReads;
  hd.discover().then((r) => {
    assert.strictEqual(r, null);
    assert.strictEqual(credReads, before, "无可探目标时不得读 apiKey 候选(磁盘重活)");
    cleanup();
    console.log("host-discover 自检 ✓ (TTL 缓存 / 失效刷新 / win32 短路 / 先廉后贵)");
  }).catch((e) => { cleanup(); console.error(e); process.exit(1); });
} catch (e) {
  cleanup();
  throw e;
}

function cleanup() {
  Object.defineProperty(process, "platform", realPlatform);
  cp.execSync = realExecSync;
  fs.readFileSync = realRead;
  os.homedir = realHomedir;
  if (realAppData === undefined) delete process.env.APPDATA;
  else process.env.APPDATA = realAppData;
}
