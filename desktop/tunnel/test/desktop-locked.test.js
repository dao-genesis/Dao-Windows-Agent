"use strict";
// 独立桌面页(锁定模式)护栏 — 分而治之:
// 带 ?account=<账号> 打开时本页只承载该账号的整块桌面, 账号选择归统一管理面(页内不再显示账号下拉)。
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "..", "desktop.html"), "utf8");

test("锁定模式要素齐备(LOCKED · 隐藏账号下拉 · 标题回显账号)", () => {
  assert.ok(html.includes("const LOCKED"), "缺 LOCKED 锁定模式判定");
  assert.ok(html.includes("Q.get('account')"), "未从 URL 读取账号");
  assert.ok(html.includes("Q.get('lock')"), "缺 lock=1 显式锁定支持");
  assert.ok(/if \(LOCKED\) \{[\s\S]*?acctEl\.style\.display = 'none';/.test(html), "锁定模式未隐藏账号下拉");
  assert.ok(html.includes('id="ttl"'), "缺标题元素(锁定时回显账号)");
});

test("锁定模式保留同账号多路能力(分身/平铺/连接/断开)与内联脚本语法完好", () => {
  for (const needle of ["addInstance()", "toggleLayout()", "doConnect()", "doDisconnect()"]) {
    assert.ok(html.includes(needle), "缺: " + needle);
  }
  const m = html.match(/<script>(?![^<]*src)([\s\S]*)<\/script>/);
  assert.ok(m, "应含内联脚本");
  assert.doesNotThrow(() => new Function(m[1]), "内联脚本必须无语法错误");
});
