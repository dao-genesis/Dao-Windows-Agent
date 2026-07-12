#!/usr/bin/env node
// ☯ devin_auth 纯逻辑自检（离线·不触网）：bridge 键完整、注入片段形状、脱敏。
'use strict';
const assert = require('assert');
const path = require('path');
const { login, buildAuthBridge, buildLoginJumpPage, CFG } = require(path.join(__dirname, '..', 'devin_auth.js'));

// 1) 官方端点常量 1:1 对齐 rt-flow devin_cloud。
assert.strictEqual(CFG.loginUrl, 'https://windsurf.com/_devin-auth/password/login');
assert.strictEqual(CFG.apiBase, 'https://app.devin.ai/api');

// 2) 注入桥必含 auth1_session + 全部 post-auth 守卫键（键名 1:1 对齐 rt-flow buildAuthBridge）。
const fakeAuth = { auth1: 'auth1_FAKE', userId: 'user-FAKE', orgId: 'org-FAKE', orgName: 'acme' };
const bridge = buildAuthBridge(fakeAuth);
for (const key of [
  "localStorage.setItem('auth1_session'",
  'migrated-to-unscoped-auth0-token-2025-12-18',
  "'known-org-ids-'+__uid",
  'last-internal-org-for-external-org-v1-null',
  'post-auth-v3-null-',
  'webapp_logged_in=true',
]) {
  assert.ok(bridge.indexOf(key) !== -1, '注入桥缺键: ' + key);
}
assert.ok(bridge.indexOf('auth1_FAKE') !== -1, '注入桥未含 auth1');
assert.ok(bridge.indexOf('user-FAKE') !== -1, '注入桥未含 userId');
assert.ok(bridge.indexOf('org-FAKE') !== -1, '注入桥未含 orgId');

// 3) 跳板页应在注入后跳 app.devin.ai。
const page = buildLoginJumpPage(fakeAuth);
assert.ok(page.indexOf('location.replace') !== -1 && page.indexOf('app.devin.ai') !== -1);

// 4) </script> 逃逸防护：orgName 内的闭合标签被拆解。
const evil = buildAuthBridge({ auth1: 'a', userId: 'u', orgId: 'o', orgName: '</script><script>x' });
assert.ok(evil.indexOf('</script><script>x') === -1, 'orgName 未做闭合逃逸');

// 5) login 是异步函数（形状），不在此触网。
assert.strictEqual(typeof login, 'function');

console.log('devin_auth.test.js OK');
