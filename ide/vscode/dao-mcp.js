// 底层工具融合(官方并列层): 把机控桥的 MCP 外壳(runtime → python -m bridge.mcp)
// 注册进宿主 IDE 的官方 mcp_config.json, 使四领域动词以官方 function-calling 工具的
// 身份与官方内建工具并列——Cascade/Devin 会话内可原生调用(list_apps/route/session_invoke…),
// 与提示词隔离/替换(dao-proxy-pro + promptShaper)同炉共冶。
// 纯逻辑(merge/entry 构造)与 IDE 副作用分离, 供 node 自检直测。
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");

const SERVER_ID = "dao-windows";

// 官方 MCP 配置文件候选(先到先得; 都不存在则用第一个)。
function configCandidates(home) {
  const h = home || os.homedir();
  return [
    path.join(h, ".codeium", "windsurf", "mcp_config.json"),
    path.join(h, ".codeium", "windsurf-next", "mcp_config.json"),
  ];
}

function pickConfigPath(home) {
  const cands = configCandidates(home);
  for (const p of cands) { if (fs.existsSync(p)) return p; }
  return cands[0];
}

// 构造 dao-windows 服务器条目: 自带 runtime 的 stdio MCP(零依赖纯标准库)。
function buildEntry({ pythonPath, runtimeDir, bridgeUrl, token }) {
  const env = {};
  if (bridgeUrl) env.DAO_WIN_BRIDGE_URL = bridgeUrl;
  if (token) env.DAO_WIN_TOKEN = token;
  const entry = {
    command: pythonPath || "python",
    args: ["-m", "bridge.mcp"],
    cwd: runtimeDir,
  };
  if (Object.keys(env).length) entry.env = env;
  return entry;
}

// 幂等合并: 保留他人条目与本条目的 disabled 状态, 仅刷新 dao-windows 的启动契约。
function mergeMcpConfig(text, entry) {
  let cfg = {};
  if (text && String(text).trim()) {
    try { cfg = JSON.parse(text); } catch (e) { cfg = {}; }
  }
  if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) cfg = {};
  cfg.mcpServers = cfg.mcpServers && typeof cfg.mcpServers === "object" ? cfg.mcpServers : {};
  const prev = cfg.mcpServers[SERVER_ID];
  const next = Object.assign({}, entry);
  if (prev && typeof prev === "object" && prev.disabled !== undefined) next.disabled = prev.disabled;
  const changed = JSON.stringify(prev) !== JSON.stringify(next);
  cfg.mcpServers[SERVER_ID] = next;
  return { cfg, changed };
}

// 落盘注册; 返回 {path, changed}。
function registerDaoMcp(opts) {
  const p = pickConfigPath(opts && opts.home);
  let text = "";
  try { text = fs.readFileSync(p, "utf8"); } catch (e) {}
  const { cfg, changed } = mergeMcpConfig(text, buildEntry(opts));
  if (changed) {
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, JSON.stringify(cfg, null, 2) + "\n");
  }
  return { path: p, changed };
}

// IDE 侧一键注册: 写配置 + 尽力经官方 LS 热刷新(RefreshMcpServers), 失败静默(重启 IDE 亦生效)。
async function activateDaoMcp(context, opts) {
  const log = (opts && opts.log) || (() => {});
  const res = registerDaoMcp({
    pythonPath: opts && opts.pythonPath,
    runtimeDir: path.join(context.extensionPath, "runtime"),
    bridgeUrl: opts && opts.bridgeUrl,
    token: opts && opts.token,
  });
  log("MCP 工具层注册" + (res.changed ? "已刷新" : "无变化") + ": " + res.path);
  if (res.changed) {
    try {
      const ls = require("./dao-ai-base/dao-cascade/ls-bridge");
      await ls.call("RefreshMcpServers", {});
      log("官方 LS 已热刷新 MCP servers");
    } catch (e) { log("LS 热刷新不可用(重启 IDE 后生效): " + e.message); }
  }
  return res;
}

module.exports = { SERVER_ID, configCandidates, pickConfigPath, buildEntry, mergeMcpConfig, registerDaoMcp, activateDaoMcp };
