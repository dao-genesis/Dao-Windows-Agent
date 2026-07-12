#!/usr/bin/env node
// ☯ 冷启动·无头登录注入（本源移植自 devin-remote/core/rt-flow：devin_cloud.login + devin_proxy.buildAuthBridge）
//
// 道法自然·无为而无不为：彻底规避 GUI 一切操作完成 Devin 登录。
//   1) 无头 POST 账密 → auth1（windsurf.com/_devin-auth/password/login）
//   2) auth1 换 org（app.devin.ai/api/users/post-auth）
//   3) 产出 SPA 登录态注入片段（localStorage['auth1_session']=...）→ Devin 网页/webview 自判已登录。
//
// 零外部依赖：仅 Node 内建 https。可在 Linux 宿主验证，可在 Windows guest 运行（Devin Desktop/VSCode 自带 node）。
//
// 用法：
//   node devin_auth.js login  <email> <password>            # → 打印 auth 束 JSON（含 auth1/userId/orgId/orgName）
//   node devin_auth.js bundle <email> <password> <out.json>  # → 无头登录并把 auth 束写盘（供注入消费）
//   node devin_auth.js bridge <auth.json> [base]             # → 由 auth 束产出 <script> 注入片段（base 默认 https://app.devin.ai）
//   node devin_auth.js inject <email> <password> <out.html>  # → 一步到位：登录 + 写出可直接打开的自登录跳板页
//
// 安全：凭据只经 stdin/参数传入、只落用户指定文件；本模块永不把明文密码写日志或仓库。

'use strict';
const https = require('https');

const CFG = {
  loginUrl: 'https://windsurf.com/_devin-auth/password/login',
  apiBase: 'https://app.devin.ai/api',
  webapp: 'https://app.devin.ai',
};

function jsonRequest(method, url, headers, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    let payload = null;
    const h = Object.assign({}, headers || {});
    if (body != null) {
      payload = typeof body === 'string' ? body : JSON.stringify(body);
      h['Content-Type'] = h['Content-Type'] || 'application/json';
      h['Content-Length'] = Buffer.byteLength(payload);
    }
    const req = https.request(
      {
        method,
        host: u.hostname,
        port: u.port || 443,
        path: u.pathname + u.search,
        headers: h,
        timeout: 30000,
      },
      (res) => {
        const chunks = [];
        res.on('data', (d) => chunks.push(d));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          let json = null;
          try { json = JSON.parse(text); } catch (e) {}
          resolve({ status: res.statusCode, json, text });
        });
      },
    );
    req.on('error', reject);
    req.on('timeout', () => req.destroy(new Error('request timeout')));
    if (payload) req.write(payload);
    req.end();
  });
}

// 无头登录：账密 → auth1 + org（1:1 对齐 rt-flow devin_cloud.login）
async function login(email, password) {
  const resp = await jsonRequest('POST', CFG.loginUrl, {}, { email, password });
  if (resp.status !== 200 || !resp.json) {
    return { ok: false, error: 'login HTTP ' + resp.status + ': ' + (resp.text || '').slice(0, 160) };
  }
  const auth1 = resp.json.token || resp.json.access_token;
  if (!auth1) return { ok: false, error: '登录响应无 token' };
  const userId = resp.json.user_id || resp.json.userId || '';
  const orgResp = await jsonRequest('POST', CFG.apiBase + '/users/post-auth', { Authorization: 'Bearer ' + auth1 }, {});
  const od = orgResp.json || {};
  const orgId = od.org_id || od.orgId || '';
  if (!orgId) return { ok: false, error: 'post-auth 无 org_id (HTTP ' + orgResp.status + ')' };
  return {
    ok: true,
    auth1,
    userId,
    orgId,
    orgBare: orgId.replace(/^org-/, ''),
    orgName: od.org_name || od.orgName || '',
    email,
    ts: Date.now(),
  };
}

function safeStr(v) {
  return String(v == null ? '' : v).replace(/[\u2028\u2029]/g, '').replace(/<\/(script)/gi, '<\\/$1');
}

// 产出登录态注入片段（键 1:1 对齐 rt-flow devin_proxy.buildAuthBridge · 端口/同源模式）。
function buildAuthBridge(auth) {
  const a1 = safeStr(auth.auth1);
  const uid = safeStr(auth.userId);
  const org = safeStr(auth.orgId);
  const orgName = safeStr(auth.orgName).replace(/['"\\<>]/g, '');
  const J = JSON.stringify;
  return (
    '<script>(function(){try{' +
    'var __a1=' + J(a1) + ';var __uid=' + J(uid) + ';var __org=' + J(org) + ';var __orgName=' + J(orgName) + ';' +
    'if(__a1){' +
    "localStorage.setItem('auth1_session',JSON.stringify({token:__a1,userId:__uid}));" +
    "localStorage.setItem('migrated-to-unscoped-auth0-token-2025-12-18','true');" +
    "if(__uid)localStorage.setItem('known-org-ids-'+__uid,JSON.stringify([__org]));" +
    "if(__org)localStorage.setItem('last-internal-org-for-external-org-v1-null',__org);" +
    "if(__org&&__uid&&__orgName){var __k='post-auth-v3-null-'+__uid+'-org_name-'+__orgName;" +
    "if(!localStorage.getItem(__k))localStorage.setItem(__k,JSON.stringify({externalOrgId:null,userId:__uid,internalOrgId:__org,orgName:__orgName,result:{resolved_external_org_id:null,org_id:__org,org_name:__orgName,is_valid_resource:true}}));}" +
    '}' +
    "document.cookie='webapp_logged_in=true; path=/; max-age=31536000; SameSite=Lax';" +
    '}catch(e){}})();</script>'
  );
}

// 自登录跳板页：注入登录态后自动跳转 Devin 网页 → 打开即已登录，零 GUI。
function buildLoginJumpPage(auth) {
  return (
    '<!doctype html><html><head><meta charset="utf-8">' +
    buildAuthBridge(auth) +
    '<script>location.replace(' + JSON.stringify(CFG.webapp + '/') + ');</script>' +
    '</head><body>☯ 已注入登录态，正在进入 Devin…</body></html>'
  );
}

async function main() {
  const [cmd, a, b, c] = process.argv.slice(2);
  const fs = require('fs');
  if (cmd === 'login') {
    const r = await login(a, b);
    process.stdout.write(JSON.stringify(r) + '\n');
    process.exit(r.ok ? 0 : 1);
  } else if (cmd === 'bundle') {
    const r = await login(a, b);
    if (!r.ok) { process.stderr.write(r.error + '\n'); process.exit(1); }
    fs.writeFileSync(c, JSON.stringify(r), { mode: 0o600 });
    process.stdout.write('auth bundle → ' + c + ' (user ' + r.userId + ' org ' + r.orgId + ')\n');
  } else if (cmd === 'bridge') {
    const auth = JSON.parse(fs.readFileSync(a, 'utf8'));
    process.stdout.write(buildAuthBridge(auth) + '\n');
  } else if (cmd === 'inject') {
    const r = await login(a, b);
    if (!r.ok) { process.stderr.write(r.error + '\n'); process.exit(1); }
    fs.writeFileSync(c, buildLoginJumpPage(r), { mode: 0o600 });
    process.stdout.write('login jump page → ' + c + ' (user ' + r.userId + ' org ' + r.orgId + ')\n');
  } else {
    process.stderr.write('usage: devin_auth.js login|bundle|bridge|inject ...\n');
    process.exit(2);
  }
}

if (require.main === module) {
  main().catch((e) => { process.stderr.write('ERR ' + (e && e.message || e) + '\n'); process.exit(1); });
}

module.exports = { login, buildAuthBridge, buildLoginJumpPage, CFG };
