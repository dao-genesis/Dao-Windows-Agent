// proxy-pro 自检（第三方模型渠道 + 模型路由，插件自持真源）：
// 预设完整 / 增删渠道 / Key 脱敏（绝不出全 Key，只回尾4） / 模型路由与连带清理 / 落盘 mode 600。
"use strict";
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "dao-pp-"));
process.env.DAO_PROXY_CHANNELS_FILE = path.join(tmp, "proxy-channels.json");

const pp = require("../dao-ai-base/dao-cascade/proxy-pro");

// 1) 预设渠道齐备（聚合/主流厂商/本地 Ollama）。
assert.ok(Array.isArray(pp.PRESETS) && pp.PRESETS.length >= 10, "预设渠道应齐备");
const names = pp.PRESETS.map((p) => p.n).join("|");
["OpenRouter", "DeepSeek", "OpenAI", "Anthropic", "Ollama"].forEach((k) =>
  assert.ok(names.indexOf(k) >= 0, "预设应含 " + k));
console.log("✓ 预设渠道齐备 (" + pp.PRESETS.length + " 家)");

// 2) 添加渠道（离线：无网络→verify=pending，不阻断）。
(async () => {
  const r = await pp.addChannel("我的DeepSeek", "openai", "https://api.deepseek.com/v1", "sk-TESTKEY1234abcd");
  assert.strictEqual(r.name, "我的DeepSeek");
  assert.ok(["pending", "ok", "bad"].indexOf(r.verify) >= 0);
  console.log("✓ 添加渠道 verify=" + r.verify);

  // 3) 脱敏视图：绝不含完整 apiKey，只回 hasKey + 尾4。
  const v = pp.listView();
  const ch = v.channels.find((c) => c.name === "我的DeepSeek");
  assert.ok(ch, "应能列出渠道");
  assert.strictEqual(ch.hasKey, true);
  assert.strictEqual(ch.keyTail, "abcd", "只回尾4");
  assert.ok(!JSON.stringify(v).includes("sk-TESTKEY1234abcd"), "视图绝不含完整 Key");
  console.log("✓ 视图脱敏：仅 hasKey+尾4，无全 Key");

  // 4) 落盘权限 600（Key 明文只存本地私有文件）。
  const mode = fs.statSync(pp.cfgPath()).mode & 0o777;
  assert.strictEqual(mode, 0o600, "配置文件应 600, 实际=" + mode.toString(8));
  console.log("✓ 配置落盘 mode 600");

  // 5) 模型路由：官方 UID → 渠道:模型；removeChannel 连带清理路由。
  pp.setRoute("official-model-uid-x", "我的DeepSeek", "deepseek-chat");
  let v2 = pp.listView();
  assert.ok(v2.routes.find((x) => x.uid === "official-model-uid-x" && x.channel === "我的DeepSeek"), "路由应生效");
  console.log("✓ 模型路由生效");

  assert.throws(() => pp.setRoute("u2", "不存在的渠道", "m"), /无此渠道/);
  pp.removeChannel("我的DeepSeek");
  let v3 = pp.listView();
  assert.strictEqual(v3.channels.length, 0, "渠道应删除");
  assert.strictEqual(v3.routes.length, 0, "指向该渠道的路由应连带清理");
  console.log("✓ 删渠道连带清理路由");

  console.log("\nPASS proxy-pro 自检");
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
