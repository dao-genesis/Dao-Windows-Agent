/**
 * HA Copilot IDE — bring the whole Home Assistant + ha_copilot capability
 * layer into VS Code:
 *
 *   • Copilot-style AI chat (streaming, tool-trace cards, stop button)
 *     backed by the ha_copilot conversation agent over the HA WebSocket API.
 *   • 本源代理 (native agent): when an external OpenAI-compatible channel is
 *     configured, the extension itself runs the agentic loop — the model
 *     schedules a Devin-Desktop-style tool layer (search_web over the nine-
 *     source HA ecosystem, list/read/write/edit config files, render_template,
 *     check_config, logs, call_service, plus run_tool into the full 2100+
 *     deterministic tool catalog) executed directly over WS/HTTP.
 *   • Areas & entities tree with one-click toggling.
 *   • hacfg:// FileSystemProvider — edit the live HA config tree in the IDE,
 *     backed by the deterministic list_dir / read_config_file /
 *     write_config_file tools.
 *   • Embedded HA panel webview and MCP config generation so any MCP client
 *     (Claude Desktop, Cline, Cursor, …) plugs into /api/ha_copilot/mcp.
 *
 * Zero runtime dependencies — Node 18+ global fetch only.
 */
"use strict";

const vscode = require("vscode");

const SECRET_TOKEN = "haCopilot.token";
const CFG = () => vscode.workspace.getConfiguration("haCopilot");

/** @type {vscode.ExtensionContext} */
let ctx;
let statusBar;
let chatProvider;
let homeProvider;

// ---------------------------------------------------------------- helpers --

function baseUrl() {
  const u = (CFG().get("baseUrl") || "").trim();
  return u.replace(/\/+$/, "");
}

async function token() {
  return (CFG().get("token") || "").trim() || (await ctx.secrets.get(SECRET_TOKEN)) || "";
}

// 默认系统规则（道法自然）：可被 haCopilot.rules.system 覆盖，haCopilot.rules.user 追加。
const DEFAULT_SYSTEM_RULE = [
  "你是 HA Copilot，IDE 里的智能家居生态操作员与架构师。处世之道：道法自然，无为而无不为——",
  "不强行、不臆测、不冗话；先观其实（查实体/配置/日志），后动其机（最小必要变更）。",
  "职责：代用户操作 Home Assistant 系统本身——设计/创建自动化与场景、配置与修复集成、",
  "搜索并导入社区蓝图、设计仪表盘、编写配置；控制设备实体只是末节。",
  "回答用中文，简洁准确；给出配置时用合法 HA YAML；不确定时先问清再动手。",
].join("");

// 本源代理 · 工具调度之道（照搬 AI 编程工具（Devin Desktop 类）本源工具层的调度纪律，
// 底层内容全部归化为 Home Assistant 板块——网络资料查九源生态、文件工具操作 HA 配置树、
// 执行层直连 ha_copilot 2100+ 确定性工具）。
const AGENT_RULE = [
  "工具调度之道：",
  "- 先观后动：动手前先以 search_tools / describe_tool / list_dir / read_file / get_logs 观其实，再动其机。",
  "- search_web 查询的是 Home Assistant 生态网络资料（HACS / 社区蓝图 / GitHub / Zigbee / Z-Wave / Tasmota / ESPHome / 官方集成 / 加载项 九源），检索社区方案与设备兼容性时先用它。",
  "- 改既有配置文件用 edit_file 做最小必要变更（old_str 必须唯一）；仅新建/整写文件才用 write_file；写完必 check_config 校验，失败则读日志修复。",
  "- render_template 可执行 Jinja2 模板做计算与实时状态查询。",
  "- run_tool 可执行工具目录中 2100+ 确定性工具的任意一个：先 search_tools 找到名字，再 describe_tool 看参数，然后调用。",
  "- 遇错不弃：读错误信息，换参数或换工具再试；连续失败才向用户求助。",
  "- 事毕直接给出简洁结论与所做变更，不复述工具原始输出。",
].join("\n");

// 本源观照 · 经藏（与 dao-proxy-pro 同源：帛书《老子》/道藏《阴符经》/二经合一）
const CANON_MAP = {
  laozi: { files: ["_silk_de.txt", "_silk_dao.txt"], name: "帛書《老子》" },
  yinfu: { files: ["_yinfu.txt"], name: "道藏《陰符經》" },
  "laozi+yinfu": { files: ["_silk_de.txt", "_silk_dao.txt", "_yinfu.txt"], name: "帛書老子+道藏陰符經" },
};
const _canonCache = {};
function canonText(canon) {
  if (_canonCache[canon] !== undefined) return _canonCache[canon];
  const entry = CANON_MAP[canon];
  const fs = require("fs"), path = require("path");
  const parts = [];
  for (const f of (entry ? entry.files : [])) {
    try { parts.push(fs.readFileSync(path.join(__dirname, "canon", f), "utf8").trim()); } catch {}
  }
  return (_canonCache[canon] = parts.join("\n\n"));
}
function canonHeader(canon) {
  const bookRef = canon === "laozi+yinfu"
    ? "帛書《老子》道藏《陰符經》"
    : (CANON_MAP[canon] ? CANON_MAP[canon].name : "帛書《老子》");
  return "你本無名 名可名也 非恆名也 所遵從之一切均來自於下述" + bookRef + "：\n\n";
}
function essenceSP(canon) {
  const body = canonText(canon);
  return body
    ? canonHeader(canon) + body + "\n\n" + DEFAULT_SYSTEM_RULE
    : DEFAULT_SYSTEM_RULE;
}
function rulesCfg() {
  const c = CFG();
  const custom = (c.get("rules.system") || "").trim();
  const mode = (c.get("rules.mode") || "dao").trim() === "plain" ? "plain" : "dao";
  let canon = (c.get("rules.canon") || "").trim();
  if (!CANON_MAP[canon]) canon = "laozi+yinfu";
  const sys = custom || (mode === "plain" ? DEFAULT_SYSTEM_RULE : essenceSP(canon));
  const user = (c.get("rules.user") || "").trim();
  return {
    system: sys, user, mode, canon,
    canonName: CANON_MAP[canon].name,
    custom: !!custom,
    prompt: user ? sys + "\n\n用户规则（优先遵守）：\n" + user : sys,
    agentPrompt:
      (user ? sys + "\n\n用户规则（优先遵守）：\n" + user : sys) + "\n\n" + AGENT_RULE,
  };
}

// ── cc-switch 预设渠道库（与 dao-proxy-pro 渠道配置面板同源）──
// 字段: n=名, u=Base URL(OpenAI 兼容), r=注册/官网(去拿 APIKey)
const CLOUD_PRESETS = [
  { n: "DeepSeek 深度求索", u: "https://api.deepseek.com/v1", r: "https://platform.deepseek.com/api_keys" },
  { n: "小米 MiMo (Xiaomi)", u: "https://api.xiaomimimo.com/v1", r: "https://platform.xiaomimimo.com" },
  { n: "智谱 GLM (Zhipu)", u: "https://open.bigmodel.cn/api/paas/v4", r: "https://open.bigmodel.cn/usercenter/apikeys" },
  { n: "Kimi 月之暗面 (Moonshot)", u: "https://api.moonshot.cn/v1", r: "https://platform.moonshot.cn/console/api-keys" },
  { n: "阿里云百炼 通义千问 (Bailian)", u: "https://dashscope.aliyuncs.com/compatible-mode/v1", r: "https://bailian.console.aliyun.com/?apiKey=1" },
  { n: "字节 豆包 火山方舟 (Doubao/Ark)", u: "https://ark.cn-beijing.volces.com/api/v3", r: "https://console.volcengine.com/ark" },
  { n: "腾讯 混元 (Hunyuan)", u: "https://api.hunyuan.cloud.tencent.com/v1", r: "https://console.cloud.tencent.com/hunyuan/api-key" },
  { n: "百度 文心千帆 (Qianfan)", u: "https://qianfan.baidubce.com/v2", r: "https://console.bce.baidu.com/iam/#/iam/apikey/list" },
  { n: "硅基流动 (SiliconFlow)", u: "https://api.siliconflow.cn/v1", r: "https://cloud.siliconflow.cn/account/ak" },
  { n: "魔搭 ModelScope", u: "https://api-inference.modelscope.cn/v1", r: "https://modelscope.cn/my/myaccesstoken" },
  { n: "MiniMax 稀宇", u: "https://api.minimaxi.com/v1", r: "https://platform.minimaxi.com/user-center/basic-information/interface-key" },
  { n: "讯飞星火 (iFlytek Spark)", u: "https://spark-api-open.xf-yun.com/v1", r: "https://console.xfyun.cn/services/cbm" },
  { n: "阶跃星辰 (StepFun)", u: "https://api.stepfun.com/v1", r: "https://platform.stepfun.com/interface-key" },
  { n: "零一万物 (01.AI Yi)", u: "https://api.lingyiwanwu.com/v1", r: "https://platform.lingyiwanwu.com/apikeys" },
  { n: "百川 (Baichuan)", u: "https://api.baichuan-ai.com/v1", r: "https://platform.baichuan-ai.com/console/apikey" },
  { n: "OpenRouter (聚合)", u: "https://openrouter.ai/api/v1", r: "https://openrouter.ai/keys" },
  { n: "OpenAI", u: "https://api.openai.com/v1", r: "https://platform.openai.com/api-keys" },
  { n: "Google Gemini", u: "https://generativelanguage.googleapis.com/v1beta/openai", r: "https://aistudio.google.com/apikey" },
  { n: "xAI Grok", u: "https://api.x.ai/v1", r: "https://console.x.ai" },
  { n: "Groq (极速)", u: "https://api.groq.com/openai/v1", r: "https://console.groq.com/keys" },
  { n: "Mistral", u: "https://api.mistral.ai/v1", r: "https://console.mistral.ai/api-keys" },
  { n: "Together AI", u: "https://api.together.xyz/v1", r: "https://api.together.xyz/settings/api-keys" },
  { n: "Fireworks AI", u: "https://api.fireworks.ai/inference/v1", r: "https://fireworks.ai/account/api-keys" },
  { n: "Perplexity", u: "https://api.perplexity.ai", r: "https://www.perplexity.ai/settings/api" },
  { n: "Ollama (本地)", u: "http://localhost:11434/v1", r: "https://ollama.com/download" },
];

// 探活 + 全量模型识别：GET {baseUrl}/models（加 Key 即自动解出该渠道所有模型）
const providerHealth = {}; // name -> { alive, models, error, at }
async function probeProvider(p) {
  const out = { alive: false, models: [], error: "", at: Date.now() };
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 12000);
    const res = await fetch(p.baseUrl.replace(/\/+$/, "") + "/models", {
      headers: { Authorization: `Bearer ${p.apiKey}` },
      signal: ctl.signal,
    });
    clearTimeout(timer);
    if (res.ok) {
      const d = await res.json().catch(() => null);
      const arr = (d && (d.data || d.models)) || [];
      out.alive = true;
      out.models = arr.map((m) => String(m.id || m.name || m)).filter(Boolean);
    } else {
      out.error = `HTTP ${res.status}`;
    }
  } catch (e) {
    out.error = String((e && e.message) || e).slice(0, 120);
  }
  providerHealth[p.name] = out;
  return out;
}

// 把自动识别出的模型列表写回 settings 中对应渠道（持久化 · 加 Key 即长效）
async function mergeProviderModels(name, models) {
  const c = CFG();
  const raw = (c.get("cloud.providers") || []).map((p) => ({ ...p }));
  const item = raw.find((p) => p && p.name === name);
  if (!item) return;
  item.models = models;
  if (!item.model && models.length) item.model = models[0];
  await c.update("cloud.providers", raw, vscode.ConfigurationTarget.Global);
}

function cloudCfg() {
  const c = CFG();
  const legacy = {
    name: "默认",
    baseUrl: (c.get("cloud.baseUrl") || "").trim().replace(/\/+$/, ""),
    apiKey: (c.get("cloud.apiKey") || "").trim(),
    model: (c.get("cloud.model") || "deepseek-chat").trim(),
  };
  let providers = (c.get("cloud.providers") || [])
    .filter((p) => p && p.baseUrl && p.apiKey)
    .map((p) => ({
      name: String(p.name || p.model || "渠道"),
      baseUrl: String(p.baseUrl).trim().replace(/\/+$/, "").replace(/\/chat\/completions$/, ""),
      apiKey: String(p.apiKey).trim(),
      model: String(p.model || "").trim(),
    }));
  if (!providers.length && legacy.baseUrl && legacy.apiKey) providers = [legacy];
  const activeName = (c.get("cloud.active") || "").trim();
  const active = providers.find((p) => p.name === activeName) || providers[0] || null;
  return {
    providers,
    activeName: active ? active.name : "",
    baseUrl: active ? active.baseUrl : "",
    apiKey: active ? active.apiKey : "",
    model: active ? active.model || "deepseek-chat" : "",
  };
}

async function setActiveProvider(name) {
  try {
    await CFG().update("cloud.active", name, vscode.ConfigurationTarget.Global);
  } catch {}
}

async function api(method, path, body) {
  const base = baseUrl();
  if (!base) throw new Error("未连接：先运行 “HA Copilot: 连接 Home Assistant”。");
  const tok = await token();
  const res = await fetch(base + path, {
    method,
    headers: {
      Authorization: `Bearer ${tok}`,
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${path}: ${text.slice(0, 300)}`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

async function runTool(tool, args) {
  const res = await api("POST", "/api/ha_copilot/run_tool", { tool, args: args || {} });
  // The endpoint wraps the payload: { tool, result: {...} }.
  const out = res && res.result !== undefined ? res.result : res;
  if (out && out.error) throw new Error(`${tool}: ${out.error}`);
  return out;
}

function setStatus(connected, detail) {
  if (!statusBar) return;
  if (connected) {
    statusBar.text = `$(home) HA 已连接`;
    statusBar.tooltip = detail || baseUrl();
  } else {
    statusBar.text = `$(plug) HA 未连接`;
    statusBar.tooltip = "点击连接 Home Assistant";
  }
  statusBar.show();
}

// ------------------------------------------------------------ connect flow --

async function cmdConnect() {
  const url = await vscode.window.showInputBox({
    prompt: "Home Assistant 地址 (URL)",
    placeHolder: "http://127.0.0.1:8123",
    value: baseUrl() || "http://127.0.0.1:8123",
    ignoreFocusOut: true,
  });
  if (!url) return;
  const tok = await vscode.window.showInputBox({
    prompt: "长效访问令牌 (Long-lived access token)",
    password: true,
    ignoreFocusOut: true,
  });
  if (!tok) return;
  await CFG().update("baseUrl", url.replace(/\/+$/, ""), vscode.ConfigurationTarget.Global);
  await ctx.secrets.store(SECRET_TOKEN, tok.trim());
  try {
    const cfg = await api("GET", "/api/config");
    setStatus(true, `${cfg.location_name} · HA ${cfg.version}`);
    vscode.window.showInformationMessage(
      `HA Copilot 已连接：${cfg.location_name} (Home Assistant ${cfg.version})`
    );
    homeProvider.refresh();
    chatProvider.pushConnection();
  } catch (e) {
    setStatus(false);
    vscode.window.showErrorMessage(`连接失败：${e.message}`);
  }
}

async function cmdDisconnect() {
  await ctx.secrets.delete(SECRET_TOKEN);
  setStatus(false);
  homeProvider.refresh();
  chatProvider.pushConnection();
  vscode.window.showInformationMessage("HA Copilot 已断开连接。");
}

// ------------------------------------------------------------- HA panel --
// 单网页多子页（网页套网页）：一个 webview 内左侧板块导航栏，每个板块一张
// 平级并排的 iframe 子网页（懒加载、切换不销毁），把整台 Home Assistant 的各大
// 原生板块路由进 IDE 中间面板。

const HA_BOARDS = [
  { key: "home", icon: "🏠", name: "主页", path: "/lovelace/0" },
  { key: "copilot", icon: "🤖", name: "Copilot 工作区", path: "/ha-copilot" },
  { key: "dashboards", icon: "🖼", name: "仪表盘设计", path: "/config/lovelace/dashboards" },
  { key: "automations", icon: "⚙️", name: "自动化与场景", path: "/config/automation/dashboard" },
  { key: "blueprints", icon: "📐", name: "蓝图", path: "/config/blueprint/dashboard" },
  { key: "devices", icon: "💡", name: "设备与实体", path: "/config/devices/dashboard" },
  { key: "integrations", icon: "🧩", name: "集成", path: "/config/integrations" },
  { key: "logs", icon: "📜", name: "日志", path: "/config/logs" },
  { key: "devtools", icon: "🛠", name: "开发者工具", path: "/developer-tools/state" },
  { key: "settings", icon: "🔧", name: "设置", path: "/config" },
  { key: "api", icon: "🔌", name: "渠道配置（外接 API）", builtin: "api" },
  { key: "rules", icon: "☯", name: "本源观照", builtin: "rules" },
];

let shellPanel = null;
let ecoBar;

function shellHtml(base) {
  const boards = JSON.stringify(HA_BOARDS);
  return /* html */ `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8" />
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{width:100%;height:100vh;overflow:hidden;background:var(--vscode-editor-background);
            color:var(--vscode-foreground);font-family:var(--vscode-font-family)}
  .app{display:flex;height:100vh}
  .sb{width:52px;background:var(--vscode-sideBar-background);border-right:1px solid var(--vscode-widget-border,#8884);
      display:flex;flex-direction:column;align-items:center;padding:8px 0;flex:none}
  .ni{width:38px;height:38px;display:flex;align-items:center;justify-content:center;border-radius:8px;
      cursor:pointer;font-size:17px;margin:2px 0;opacity:.6}
  .ni:hover{opacity:1;background:var(--vscode-toolbar-hoverBackground,#8883)}
  .ni.active{opacity:1;background:var(--vscode-button-background);}
  .mn{flex:1;display:flex;flex-direction:column;overflow:hidden}
  .hd{padding:6px 12px;border-bottom:1px solid var(--vscode-widget-border,#8884);display:flex;gap:8px;
      align-items:center;font-size:12px;flex:none;background:var(--vscode-sideBar-background)}
  .hd .t{font-weight:600;font-size:13px}
  .hd .u{opacity:.6}
  .hd input{margin-left:auto;flex:1;max-width:340px;background:var(--vscode-input-background);
         color:var(--vscode-input-foreground);border:1px solid var(--vscode-input-border,#8884);
         border-radius:4px;padding:2px 8px;font-size:12px}
  .hd .r{background:transparent;border:1px solid var(--vscode-widget-border,#8884);
         color:var(--vscode-foreground);border-radius:4px;padding:1px 8px;cursor:pointer}
  .ct{flex:1;position:relative}
  .tv{position:absolute;inset:0;display:none}
  .tv.active{display:block}
  .tv iframe{width:100%;height:100%;border:0;background:#fff}
  .bi{position:absolute;inset:0;overflow:auto;padding:18px 22px;display:none}
  .bi.active{display:block}
  .bi h2{font-size:15px;margin-bottom:10px}
  .bi .card{border:1px solid var(--vscode-widget-border,#8884);border-radius:8px;padding:10px 12px;margin:8px 0;
            background:var(--vscode-editorWidget-background)}
  .bi label{display:block;font-size:11px;opacity:.75;margin:6px 0 2px}
  .bi input,.bi textarea{width:100%;background:var(--vscode-input-background);color:var(--vscode-input-foreground);
     border:1px solid var(--vscode-input-border,#8884);border-radius:4px;padding:4px 8px;font-size:12px;
     font-family:inherit}
  .bi textarea{min-height:110px;resize:vertical}
  .bi button{background:var(--vscode-button-background);color:var(--vscode-button-foreground);border:0;
     border-radius:5px;padding:4px 14px;cursor:pointer;margin:8px 6px 0 0;font-size:12px}
  .bi button.sec{background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}
  .bi .row{display:flex;gap:8px}.bi .row>div{flex:1}
  .bi .tag{font-size:10px;border:1px solid var(--vscode-widget-border,#8884);border-radius:8px;padding:1px 7px;
           opacity:.75;margin-left:6px}
  .bi .hint{font-size:11px;opacity:.6;margin-top:6px}
  .bi select{background:var(--vscode-input-background);color:var(--vscode-input-foreground);
     border:1px solid var(--vscode-input-border,#8884);border-radius:4px;padding:4px 6px;font-size:12px;
     font-family:inherit;outline:none}
  .bi .bar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:6px 0}
  .bi .bar input{width:auto}
  .bi .sbtn{background:transparent;border:1px solid var(--vscode-widget-border,#8884);
     color:var(--vscode-foreground);border-radius:4px;padding:2px 8px;cursor:pointer;font-size:11px;margin:0}
  .bi .sbtn:hover{background:var(--vscode-toolbar-hoverBackground,#8883)}
  .bi .dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none;margin-top:5px}
  .bi .chan{display:flex;gap:8px;align-items:flex-start;border:1px solid var(--vscode-widget-border,#8884);
     border-radius:6px;padding:7px 9px;margin:5px 0;background:var(--vscode-editorWidget-background)}
  .bi .chan.act{border-color:var(--vscode-button-background)}
  .bi pre{white-space:pre-wrap;word-break:break-word;font-size:11px;line-height:1.5;
     background:var(--vscode-textCodeBlock-background,rgba(0,0,0,.18));border-radius:4px;padding:8px;
     max-height:300px;overflow:auto}
</style></head>
<body>
<div class="app">
  <div class="sb" id="sb"></div>
  <div class="mn">
    <div class="hd"><span class="t" id="title"></span><span class="u">${base}</span>
      <input id="nav" placeholder="输入任意路径或完整 URL 新开板块，如 /energy 或 http://127.0.0.1:xxxx，回车" />
      <button class="r" id="reload" title="重载当前板块">⟳</button></div>
    <div class="ct" id="ct"></div>
  </div>
</div>
<script>
const vscodeApi = acquireVsCodeApi();
const BASE = ${JSON.stringify(base)};
const BOARDS = ${boards};
const sb = document.getElementById("sb"), ct = document.getElementById("ct");
const title = document.getElementById("title");
let cur = null;
function show(key) {
  cur = key;
  const b = BOARDS.find((x) => x.key === key);
  if (!b) return;
  title.textContent = b.icon + " " + b.name;
  for (const el of sb.children) el.classList.toggle("active", el.dataset.key === key);
  let tv = document.getElementById("tv-" + key);
  if (!tv) {
    if (b.builtin) {
      tv = document.createElement("div"); tv.className = "bi tv"; tv.id = "tv-" + key;
      tv.innerHTML = b.builtin === "api" ? apiBoardHtml() : rulesBoardHtml();
      ct.appendChild(tv);
      if (b.builtin === "api") wireApiBoard(tv); else wireRulesBoard(tv);
      vscodeApi.postMessage({ type: "cfg" });
    } else {
      tv = document.createElement("div"); tv.className = "tv"; tv.id = "tv-" + key;
      const f = document.createElement("iframe");
      f.src = /^https?:/.test(b.path) ? b.path : BASE + b.path; f.allow = "fullscreen";
      tv.appendChild(f); ct.appendChild(tv);
    }
  }
  for (const el of ct.children) el.classList.toggle("active", el.id === "tv-" + key);
}

// ---------- 内置板块（与 dao-proxy-pro 同源移植）：② 渠道配置 (cc-switch 风) + ① 本源观照 ----------
let cfgData = { providers: [], active: "", presets: [], health: {},
                rules: { mode: "dao", canon: "laozi+yinfu", canonName: "", custom: false,
                         system: "", user: "", effective: "", defaultPlain: "" } };
function escA(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;"); }

// ── ② 渠道配置 ──
function apiBoardHtml() {
  return '<h2>\ud83d\udd0c 渠道配置 <span class="tag">cc-switch 风 · OpenAI 兼容 · 运行时切换</span></h2>' +
    '<div class="bar">' +
      '<select id="presetSel" style="flex:1;min-width:140px"><option value="">— 选择预设渠道 (cc-switch) —</option></select>' +
      '<button class="sbtn" id="btnFillPreset" title="填入下方表单">填入预设</button>' +
      '<button class="sbtn" id="btnRegister" title="打开该渠道官网/注册页 · 去拿 APIKey">\ud83c\udf10 注册/官网</button>' +
    '</div>' +
    '<div class="bar">' +
      '<input id="pName" placeholder="名称 (如 deepseek)" style="flex:.6;min-width:70px">' +
      '<input id="pUrl" placeholder="Base URL (如 https://api.deepseek.com/v1)" style="flex:2">' +
      '<input id="pKey" type="password" placeholder="API Key" style="flex:1">' +
      '<input id="pModel" placeholder="模型 (留空=自动识别该渠道全部)" style="flex:1.2">' +
      '<button class="sbtn" id="btnAddProv" title="添加/更新渠道 · 加 Key 即自动全量识别模型">＋ 添加</button>' +
      '<button class="sbtn" id="btnProbe" title="探测所有渠道健康 + 自动识别模型">探测</button>' +
      '<button class="sbtn" id="btnOpenCfg" title="在编辑器打开 settings.json · 直接查看/手改全部渠道">\ud83d\udcc4 配置JSON</button>' +
    '</div>' +
    '<div id="probeStat" class="hint"></div>' +
    '<div id="chanList"></div>';
}
function renderChannels(tv) {
  const box = tv.querySelector("#chanList");
  if (!box) return;
  if (!cfgData.providers.length) {
    box.innerHTML = '<div class="hint" style="font-style:italic;padding:6px">暂无渠道 · 选预设或手动添加</div>';
    return;
  }
  box.innerHTML = cfgData.providers.map((p, i) => {
    const h = cfgData.health[p.name];
    const dot = h ? (h.alive ? "#6bb86b" : "#e08080") : "rgba(128,128,128,.5)";
    const act = p.name === cfgData.active;
    const models = (p.models || []).length
      ? '<div style="font-size:10px;opacity:.5">' + escA(p.models.slice(0, 8).join(", ")) +
        (p.models.length > 8 ? " … 共" + p.models.length + "个" : "") + "</div>" : "";
    const err = h && !h.alive && h.error
      ? '<div style="font-size:10px;color:#e08080">✖ ' + escA(h.error) + "</div>" : "";
    return '<div class="chan' + (act ? " act" : "") + '" data-i="' + i + '">' +
      '<span class="dot" style="background:' + dot + '"></span>' +
      '<span style="flex:1;overflow:hidden">' +
        '<span style="font-weight:600">' + escA(p.name) + "</span>" +
        (act ? ' <span class="tag">✔ 当前启用</span>' : "") +
        '<div style="font-size:10px;opacity:.55;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
          escA(p.baseUrl) + " · " + escA(p.model || "自动") + "</div>" + models + err +
      "</span>" +
      (act ? "" : '<button class="sbtn c-act" title="启用此渠道">启用</button>') +
      '<button class="sbtn c-mod" title="识别该渠道全部模型">↻ 模型</button>' +
      '<button class="sbtn c-edit" title="编辑（填入上方表单）">✎</button>' +
      '<button class="sbtn c-del" title="删除">✖</button>' +
    "</div>";
  }).join("");
  for (const row of box.querySelectorAll(".chan")) {
    const i = +row.dataset.i, p = cfgData.providers[i];
    const on = (cls, fn) => { const b = row.querySelector(cls); if (b) b.onclick = fn; };
    on(".c-act", () => { cfgData.active = p.name; saveProviders(tv); });
    on(".c-mod", () => vscodeApi.postMessage({ type: "discover", name: p.name }));
    on(".c-edit", () => {
      tv.querySelector("#pName").value = p.name; tv.querySelector("#pUrl").value = p.baseUrl;
      tv.querySelector("#pKey").value = p.apiKey; tv.querySelector("#pModel").value = p.model || "";
    });
    on(".c-del", () => { cfgData.providers.splice(i, 1); saveProviders(tv); });
  }
}
function saveProviders(tv) {
  if (!cfgData.providers.find((p) => p.name === cfgData.active))
    cfgData.active = (cfgData.providers[0] && cfgData.providers[0].name) || "";
  vscodeApi.postMessage({ type: "saveProviders", providers: cfgData.providers, active: cfgData.active });
}
function wireApiBoard(tv) {
  const sel = tv.querySelector("#presetSel");
  tv.querySelector("#btnFillPreset").onclick = () => {
    const p = cfgData.presets[+sel.value];
    if (!p) return;
    tv.querySelector("#pName").value = p.n; tv.querySelector("#pUrl").value = p.u;
    tv.querySelector("#pKey").focus();
  };
  tv.querySelector("#btnRegister").onclick = () => {
    const p = cfgData.presets[+sel.value];
    if (p) vscodeApi.postMessage({ type: "openUrl", url: p.r || p.u });
  };
  tv.querySelector("#btnAddProv").onclick = () => {
    const name = tv.querySelector("#pName").value.trim();
    const baseUrl = tv.querySelector("#pUrl").value.trim().replace(/\\/+$/, "");
    const apiKey = tv.querySelector("#pKey").value.trim();
    const model = tv.querySelector("#pModel").value.trim();
    if (!name || !baseUrl || !apiKey) { tv.querySelector("#probeStat").textContent = "✖ 名称 / Base URL / API Key 均必填"; return; }
    const i = cfgData.providers.findIndex((p) => p.name === name);
    const item = { name, baseUrl, apiKey, model, models: i >= 0 ? cfgData.providers[i].models || [] : [] };
    if (i >= 0) cfgData.providers[i] = item; else cfgData.providers.push(item);
    if (!cfgData.active) cfgData.active = name;
    saveProviders(tv);
    vscodeApi.postMessage({ type: "discover", name });
    tv.querySelector("#pKey").value = ""; tv.querySelector("#probeStat").textContent = "已保存 · 正在自动识别该渠道全部模型…";
  };
  tv.querySelector("#btnProbe").onclick = () => {
    tv.querySelector("#probeStat").textContent = "探测中…";
    vscodeApi.postMessage({ type: "probe" });
  };
  tv.querySelector("#btnOpenCfg").onclick = () => vscodeApi.postMessage({ type: "openSettings" });
  renderChannels(tv);
}
function fillPresets(tv) {
  const sel = tv.querySelector("#presetSel");
  if (!sel || sel.options.length > 1) return;
  cfgData.presets.forEach((p, i) => {
    const o = document.createElement("option");
    o.value = String(i); o.textContent = p.n + " · " + p.u;
    sel.appendChild(o);
  });
}

// ── ① 本源观照 ──
let essEditOpen = false;
function rulesBoardHtml() {
  return '<h2>\u262f 本源观照 <span class="tag">帛书经藏前置 · 道法自然</span></h2>' +
    '<div class="bar">' +
      '<span id="essDot" class="dot" style="margin-top:0;background:rgba(128,128,128,.4)"></span>' +
      '<button class="sbtn" id="essDao" title="道 · 帛书经藏前置注入" style="font-weight:600">道</button>' +
      '<button class="sbtn" id="essPlain" title="官 · 仅操作规则 · 无经藏前置">官</button>' +
      '<button class="sbtn" id="essEdit" title="编 · 编辑注入 LLM 之系统提示词">编</button>' +
      '<select id="essCanon" title="经藏切换 · 两经归一 · 道生一">' +
        '<option value="laozi+yinfu">帛书老子+道藏阴符经</option>' +
        '<option value="laozi">帛书《老子》</option>' +
        '<option value="yinfu">道藏《阴符经》</option>' +
      '</select>' +
      '<span id="essBadge" style="font-size:10px;opacity:.6"></span>' +
    '</div>' +
    '<div id="essStat" class="hint">本源观照 · 加载中…</div>' +
    '<pre id="essSp">（加载中）</pre>' +
    '<div id="essEditArea" style="display:none">' +
      '<div class="hint">编此 · 改注入 LLM 之系统提示词 · Ctrl+Enter 保存 · 留空并注入 = 归道（回内置经藏路径）</div>' +
      '<textarea id="essText" style="min-height:150px;font-family:var(--vscode-editor-font-family,monospace)"></textarea>' +
      '<button id="essSave" title="保存注入 (Ctrl+Enter)">✔ 注入</button>' +
      '<button class="sec" id="essLoad" title="载入当前实际生效 SP（不保存）">载</button>' +
      '<button class="sec" id="essReset" title="清自定义 · 回默认经藏路径">✖ 归道</button>' +
      '<span id="essEditStat" class="hint"></span>' +
    '</div>' +
    '<div class="card"><label>用户规则（追加在系统提示词之后 · 优先遵守 · 一般用户用不到）</label>' +
    '<textarea id="rUser"></textarea>' +
    '<button id="saveUser">保存用户规则</button></div>';
}
function fillEssence(tv) {
  const r = cfgData.rules;
  const dao = r.mode !== "plain";
  tv.querySelector("#essDot").style.background = dao ? "#6bb86b" : "#d9a441";
  tv.querySelector("#essDao").style.opacity = dao ? "1" : ".5";
  tv.querySelector("#essPlain").style.opacity = dao ? ".5" : "1";
  tv.querySelector("#essCanon").value = r.canon;
  tv.querySelector("#essBadge").textContent = r.custom ? "✎ 自定义" : "";
  tv.querySelector("#essStat").textContent =
    "模式 " + (dao ? "道" : "官") + " · 经藏 " + (r.canonName || r.canon) +
    " · 本源体 " + (r.effective || "").length + " 字 · " +
    (r.custom ? "自定义 SP 生效" : "默认经藏路径");
  tv.querySelector("#essSp").textContent = r.effective || "（空）";
  tv.querySelector("#rUser").value = r.user || "";
}
function wireRulesBoard(tv) {
  const post = (patch) => vscodeApi.postMessage(Object.assign({ type: "saveEssence" }, patch));
  tv.querySelector("#essDao").onclick = () => post({ mode: "dao" });
  tv.querySelector("#essPlain").onclick = () => post({ mode: "plain" });
  tv.querySelector("#essCanon").onchange = (e) => post({ canon: e.target.value });
  const tx = tv.querySelector("#essText"), st = tv.querySelector("#essEditStat");
  tv.querySelector("#essEdit").onclick = () => {
    essEditOpen = !essEditOpen;
    tv.querySelector("#essEditArea").style.display = essEditOpen ? "block" : "none";
    if (essEditOpen) {
      tx.value = cfgData.rules.custom ? cfgData.rules.system : cfgData.rules.effective;
      st.textContent = cfgData.rules.custom ? "当前为自定义 SP" : "当前为默认经藏路径（改后注入即为自定义）";
      tx.focus();
    }
  };
  const save = () => { post({ system: tx.value }); st.textContent = "注入中…"; };
  tv.querySelector("#essSave").onclick = save;
  tv.querySelector("#essLoad").onclick = () => { tx.value = cfgData.rules.effective; st.textContent = "已载实际生效 SP（未保存）"; };
  tv.querySelector("#essReset").onclick = () => { post({ system: "" }); st.textContent = "归道中…"; };
  tx.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") { ev.preventDefault(); save(); }
    else if (ev.key === "Escape") { essEditOpen = false; tv.querySelector("#essEditArea").style.display = "none"; }
  });
  tv.querySelector("#saveUser").onclick = () => post({ user: tv.querySelector("#rUser").value });
}

function fillBuiltins() {
  const apiTv = document.getElementById("tv-api");
  if (apiTv) { fillPresets(apiTv); renderChannels(apiTv); }
  const rTv = document.getElementById("tv-rules");
  if (rTv) fillEssence(rTv);
}
window.addEventListener("message", (ev) => {
  const m = ev.data;
  if (m.type === "cfg") { cfgData = m.data; fillBuiltins(); }
  else if (m.type === "probeDone") {
    cfgData.health = m.health || {};
    const apiTv = document.getElementById("tv-api");
    if (apiTv) {
      const alive = Object.values(cfgData.health).filter((h) => h.alive).length;
      apiTv.querySelector("#probeStat").textContent =
        "探测完成 · " + alive + "/" + Object.keys(cfgData.health).length + " 通";
      renderChannels(apiTv);
    }
  }
  else if (m.type === "saved") {
    const rTv = document.getElementById("tv-rules");
    const st = rTv && rTv.querySelector("#essEditStat");
    if (st && essEditOpen) st.textContent = "✔ 已注入 · 下次对话生效";
  }
});
for (const b of BOARDS) {
  const el = document.createElement("div");
  el.className = "ni"; el.dataset.key = b.key; el.title = b.name; el.textContent = b.icon;
  el.onclick = () => show(b.key);
  sb.appendChild(el);
}
let dynSeq = 0;
document.getElementById("nav").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  let p = e.target.value.trim();
  if (!p) return;
  if (!/^https?:/.test(p) && !p.startsWith("/")) p = "/" + p;
  const key = "dyn" + (++dynSeq);
  BOARDS.push({ key, icon: "📌", name: p, path: p });
  const el = document.createElement("div");
  el.className = "ni"; el.dataset.key = key; el.title = p; el.textContent = "📌";
  el.onclick = () => show(key);
  sb.appendChild(el);
  e.target.value = "";
  show(key);
});
document.getElementById("reload").onclick = () => {
  const tv = document.getElementById("tv-" + cur);
  const f = tv && tv.querySelector("iframe");
  if (f) f.src = f.src;
};
show("home");
</script>
</body></html>`;
}

function panelBase() {
  return (CFG().get("panelUrl") || "").trim().replace(/\/+$/, "") || baseUrl();
}

function updateEcoBar() {
  if (!ecoBar) return;
  ecoBar.text = shellPanel ? "$(circle-filled) 关闭生态" : "$(globe) 打开生态";
  ecoBar.tooltip = "一键打开/关闭生态面板（单网页）";
  ecoBar.show();
}

function cmdOpenPanel() {
  const base = panelBase();
  if (!base) return vscode.window.showErrorMessage("先连接 Home Assistant 或设置 haCopilot.panelUrl。");
  if (shellPanel) {
    shellPanel.reveal();
    return;
  }
  shellPanel = vscode.window.createWebviewPanel(
    "haCopilotPanel",
    "生态面板",
    vscode.ViewColumn.Active,
    { enableScripts: true, retainContextWhenHidden: true }
  );
  shellPanel.onDidDispose(() => { shellPanel = null; updateEcoBar(); });
  shellPanel.webview.html = shellHtml(base);
  const pushCfg = () => {
    const c = CFG();
    const r = rulesCfg();
    shellPanel?.webview.postMessage({ type: "cfg", data: {
      providers: c.get("cloud.providers") || [],
      active: (c.get("cloud.active") || "").trim() || cloudCfg().activeName,
      presets: CLOUD_PRESETS,
      health: providerHealth,
      rules: { mode: r.mode, canon: r.canon, canonName: r.canonName, custom: r.custom,
               system: (c.get("rules.system") || "").trim(), user: r.user,
               effective: r.system, defaultPlain: DEFAULT_SYSTEM_RULE },
    } });
  };
  shellPanel.webview.onDidReceiveMessage(async (msg) => {
    const c = CFG();
    if (msg.type === "cfg") {
      pushCfg();
    } else if (msg.type === "saveProviders") {
      await c.update("cloud.providers", msg.providers, vscode.ConfigurationTarget.Global);
      await c.update("cloud.active", msg.active, vscode.ConfigurationTarget.Global);
      chatProvider?.pushConnection();
      shellPanel?.webview.postMessage({ type: "saved" });
      pushCfg();
    } else if (msg.type === "saveEssence") {
      if (msg.mode !== undefined) await c.update("rules.mode", msg.mode, vscode.ConfigurationTarget.Global);
      if (msg.canon !== undefined) await c.update("rules.canon", msg.canon, vscode.ConfigurationTarget.Global);
      if (msg.system !== undefined) await c.update("rules.system", String(msg.system).trim(), vscode.ConfigurationTarget.Global);
      if (msg.user !== undefined) await c.update("rules.user", String(msg.user).trim(), vscode.ConfigurationTarget.Global);
      chatProvider?.pushConnection();
      shellPanel?.webview.postMessage({ type: "saved" });
      pushCfg();
    } else if (msg.type === "probe") {
      const provs = cloudCfg().providers;
      await Promise.all(provs.map(async (p) => {
        const h = await probeProvider(p);
        if (h.alive && h.models.length) await mergeProviderModels(p.name, h.models);
      }));
      shellPanel?.webview.postMessage({ type: "probeDone", health: providerHealth });
      pushCfg();
    } else if (msg.type === "discover") {
      const p = cloudCfg().providers.find((x) => x.name === msg.name);
      if (p) {
        const h = await probeProvider(p);
        if (h.alive && h.models.length) await mergeProviderModels(p.name, h.models);
        shellPanel?.webview.postMessage({ type: "probeDone", health: providerHealth });
        pushCfg();
      }
    } else if (msg.type === "openUrl") {
      if (msg.url) vscode.env.openExternal(vscode.Uri.parse(String(msg.url)));
    } else if (msg.type === "openSettings") {
      vscode.commands.executeCommand("workbench.action.openSettingsJson");
    }
  });
  updateEcoBar();
}

function cmdTogglePanel() {
  if (shellPanel) { shellPanel.dispose(); return; }
  cmdOpenPanel();
}

// -------------------------------------------- external LLM API (options flow) --
// 把任意 OpenAI 兼容的第三方 API 原生接入 ha_copilot 底层（config-entry 选项流）。

async function cmdConfigureLlm() {
  if (!baseUrl() || !(await token())) return vscode.window.showErrorMessage("先连接 Home Assistant。");
  try {
    const entries = await api("GET", "/api/config/config_entries/entry?domain=ha_copilot");
    const entry = (Array.isArray(entries) ? entries : entries.entries || []).find(
      (e) => e.domain === "ha_copilot"
    );
    if (!entry) return vscode.window.showErrorMessage("未找到 ha_copilot 集成（先在 HA 中启用）。");
    const cur = entry.options || {};
    const base_url = await vscode.window.showInputBox({
      prompt: "云端 LLM API Base URL（OpenAI 兼容，如 https://api.openai.com/v1 、https://api.deepseek.com/v1 、https://dashscope.aliyuncs.com/compatible-mode/v1）",
      value: cur.llm_base_url || "",
      ignoreFocusOut: true,
    });
    if (base_url === undefined) return;
    const api_key = await vscode.window.showInputBox({
      prompt: "API Key（没有则留空）",
      password: true,
      ignoreFocusOut: true,
    });
    if (api_key === undefined) return;
    const model = await vscode.window.showInputBox({
      prompt: "模型名（如 gpt-4o-mini / deepseek-chat / qwen-plus）",
      value: cur.llm_model || "",
      ignoreFocusOut: true,
    });
    if (model === undefined) return;
    const flow = await api("POST", "/api/config/config_entries/options/flow", {
      handler: entry.entry_id,
    });
    const fields = {};
    for (const f of (flow.data_schema || [])) fields[f.name] = cur[f.name];
    fields.llm_base_url = base_url.trim();
    if (api_key.trim()) fields.llm_api_key = api_key.trim();
    fields.llm_model = model.trim();
    const done = await api("POST", `/api/config/config_entries/options/flow/${flow.flow_id}`, fields);
    if (done.type === "create_entry") {
      vscode.window.showInformationMessage(
        `外接模型 API 已接入底层：${model || "(未设模型)"} @ ${base_url || "(未设地址)"}`
      );
    } else {
      vscode.window.showWarningMessage(`选项流未完成：${JSON.stringify(done).slice(0, 200)}`);
    }
  } catch (e) {
    vscode.window.showErrorMessage(`配置外接模型失败：${e.message}`);
  }
}

// ------------------------------------------------------- agent access doc --
// 生成一份面向成熟 Agent 的 MD 接入文档：拿着这一份文档（+token）即可经
// HTTP/WS/MCP 五条底层全方位操作这台 Home Assistant。

async function cmdAgentDoc() {
  const base = baseUrl();
  if (!base) return vscode.window.showErrorMessage("先连接 Home Assistant。");
  let info = {};
  try { info = await api("GET", "/api/config"); } catch {}
  const md = `# HA-Copilot · Agent 接入文档（自动生成）

> 把本文档交给任意成熟 Agent（Devin / Claude / 自建 Agent），配合一个 HA 长效令牌，
> 即可直接接入这台 Home Assistant 的 ha_copilot 底层，**代替用户操作 Home Assistant 系统本身**：
> 设计/创建自动化、配置与修复集成、搜索并导入社区蓝图、设计仪表盘、开发配置——
> 用户能在 UI 里做的一切，你做得更快更好。操作设备实体只是最末节。

- 实例：\`${base}\`${info.location_name ? `（${info.location_name} · HA ${info.version}）` : ""}
- 鉴权：所有请求带 \`Authorization: Bearer <长效令牌>\`（HA 个人设置 → 长效访问令牌）。

## 五条底层（同一套工具层，五路暴露）

| 底层 | 入口 | 说明 |
|---|---|---|
| HTTP | \`GET ${base}/api/ha_copilot/tools\` | 工具目录（名称+描述） |
| HTTP | \`POST ${base}/api/ha_copilot/run_tool\` · body \`{"tool": "...", "args": {...}}\` | 执行工具；响应包 \`{tool, result}\`，错误在 \`result.error\`（HTTP 200） |
| WebSocket | \`${base.replace(/^http/, "ws")}/api/websocket\` · 命令 \`ha_copilot/tools\` / \`ha_copilot/run_tool\` / \`ha_copilot/info\` | 实时通道；另可订阅 \`ha_copilot_turn\` 事件看对话流 |
| MCP | \`${base}/api/ha_copilot/mcp\`（JSON-RPC 2.0，SSE：\`/api/ha_copilot/mcp/sse\`） | 任意 MCP 客户端直接发现/调用全部工具 |
| 原生服务 | \`ha_copilot.run_tool\` 等 13 个 HA 服务 | 自动化/脚本内直调 |

## 先用四个本源原语（一术演万法，优先于特化工具）

- \`query_entities\`（阴/观）：按 domain / 名字子串 / device_class / state / attributes 筛实体。
- \`control_entities\`（阳/动）：同一套筛选选中后一次性调服务；\`dry_run\` 可预览。
- \`aggregate_entities\`（量/数）：同一套筛选归约为数字（总数/sum/avg/on_count/分布）。
- \`search_tools\` → \`describe_tools\` → \`run_tool\`：需要特化工具时先搜后查再调。

## 示例

\`\`\`bash
# 列目录
curl -s -H "Authorization: Bearer $TOK" ${base}/api/ha_copilot/tools | head
# 开灯（模糊名称也可，dispatch 会解析并跨域重定向）
curl -s -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \\
  -d '{"tool":"control_entities","args":{"name":"门廊","service":"turn_on"}}' \\
  ${base}/api/ha_copilot/run_tool
\`\`\`

## 系统级操作（本源职责，优先于实体控制）

| 目标 | 工具举例 |
|---|---|
| 设计/创建自动化 | \`automation_create_state\` / \`automation_create_time\` / \`automation_create_sun\` / \`automation_validate_yaml\` / \`automation_suggest_improvements\` / \`audit_automations\` |
| 社区资源与蓝图 | \`search_blueprints\` / \`search_community_resources\` / \`search_github\` / \`blueprint_import\` / \`search_ha_integrations\` / \`search_ha_addons\` |
| 集成配置与修复 | \`integration_health_check\` / \`integration_list_failed\` / \`integration_reload\` / \`config_entry_health\` / \`repairs_list\` / \`repairs_fix\` |
| 仪表盘设计 | \`lovelace_get_dashboards\` / \`get_dashboard_config\` / \`update_dashboard\` / \`dashboard_entity_suggestions\` |
| 配置开发 | \`list_dir\` / \`read_config_file\` / \`write_config_file\` / \`check_config\` / \`render_template\` |

## 配置文件读写

\`list_dir\` / \`read_config_file\` / \`write_config_file\`（受 \`allow_write\` 开关约束）。

## MCP 客户端配置片段

\`\`\`json
{"mcpServers":{"ha-copilot":{"url":"${base}/api/ha_copilot/mcp/sse","transport":"sse","headers":{"Authorization":"Bearer <TOKEN>"}}}}
\`\`\`
`;
  const doc = await vscode.workspace.openTextDocument({ language: "markdown", content: md });
  vscode.window.showTextDocument(doc, { preview: true });
}

// --------------------------------------------------- hacfg:// file system --

class HaConfigFs {
  constructor() {
    this._emitter = new vscode.EventEmitter();
    this.onDidChangeFile = this._emitter.event;
  }
  watch() {
    return new vscode.Disposable(() => {});
  }
  async stat(uri) {
    const p = uri.path.replace(/^\/+/, "");
    if (!p) return { type: vscode.FileType.Directory, ctime: 0, mtime: 0, size: 0 };
    const parent = p.split("/").slice(0, -1).join("/");
    const name = p.split("/").pop();
    const res = await runTool("list_dir", { path: parent });
    const entries = res.entries || res.result?.entries || [];
    const hit = entries.find((e) => (e.name || e) === name);
    if (!hit) throw vscode.FileSystemError.FileNotFound(uri);
    const isDir = typeof hit === "object" ? hit.is_dir || hit.type === "dir" : false;
    return {
      type: isDir ? vscode.FileType.Directory : vscode.FileType.File,
      ctime: 0,
      mtime: Date.now(),
      size: (typeof hit === "object" && hit.size) || 0,
    };
  }
  async readDirectory(uri) {
    const p = uri.path.replace(/^\/+/, "");
    const res = await runTool("list_dir", { path: p });
    const entries = res.entries || res.result?.entries || [];
    return entries.map((e) => {
      const name = typeof e === "object" ? e.name : e;
      const isDir = typeof e === "object" ? e.is_dir || e.type === "dir" : false;
      return [name, isDir ? vscode.FileType.Directory : vscode.FileType.File];
    });
  }
  async readFile(uri) {
    const p = uri.path.replace(/^\/+/, "");
    const res = await runTool("read_config_file", { path: p });
    const text = res.content ?? res.result?.content ?? "";
    return Buffer.from(String(text), "utf8");
  }
  async writeFile(uri, content) {
    const p = uri.path.replace(/^\/+/, "");
    await runTool("write_config_file", {
      path: p,
      content: Buffer.from(content).toString("utf8"),
    });
    this._emitter.fire([{ type: vscode.FileChangeType.Changed, uri }]);
  }
  async createDirectory() {
    throw vscode.FileSystemError.NoPermissions("目录创建请在 HA 主机上执行。");
  }
  async delete() {
    throw vscode.FileSystemError.NoPermissions("删除请在 HA 主机上执行。");
  }
  async rename() {
    throw vscode.FileSystemError.NoPermissions("重命名请在 HA 主机上执行。");
  }
}

function cmdMountConfig() {
  const uri = vscode.Uri.parse("hacfg:/");
  const folders = vscode.workspace.workspaceFolders || [];
  if (folders.some((f) => f.uri.scheme === "hacfg")) {
    return vscode.window.showInformationMessage("HA 配置目录已挂载。");
  }
  vscode.workspace.updateWorkspaceFolders(folders.length, 0, {
    uri,
    name: "HA Config",
  });
}

// ---------------------------------------------------------- entities tree --

class HomeTreeProvider {
  constructor() {
    this._emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._emitter.event;
    this._states = new Map();
    this._pollSnapshot = null;
    this._pollTimer = null;
  }
  refresh() {
    this._states.clear();
    this._emitter.fire(undefined);
  }
  startLiveSync() {
    if (this._pollTimer) return;
    this._pollTimer = setInterval(() => this._poll(), 8000);
  }
  stopLiveSync() {
    if (this._pollTimer) clearInterval(this._pollTimer);
    this._pollTimer = null;
    this._pollSnapshot = null;
  }
  async _poll() {
    if (!baseUrl() || !(await token())) return;
    try {
      const res = await runTool("query_entities", { limit: 2000 });
      const snap = new Map();
      for (const e of res.entities || []) snap.set(e.entity_id, e.state);
      if (this._pollSnapshot) {
        let changed = this._pollSnapshot.size !== snap.size;
        if (!changed) {
          for (const [id, st] of snap) {
            if (this._pollSnapshot.get(id) !== st) { changed = true; break; }
          }
        }
        if (changed) this.refresh();
      }
      this._pollSnapshot = snap;
    } catch {
      /* transient — keep polling */
    }
  }
  async _stateOf(entityId) {
    if (this._states.size === 0) {
      const res = await runTool("query_entities", { limit: 2000 });
      for (const e of res.entities || []) this._states.set(e.entity_id, e);
    }
    return this._states.get(entityId);
  }
  getTreeItem(el) {
    return el;
  }
  async getChildren(el) {
    if (!baseUrl() || !(await token())) {
      const item = new vscode.TreeItem("未连接 — 点击连接 Home Assistant");
      item.command = { command: "haCopilot.connect", title: "connect" };
      return el ? [] : [item];
    }
    try {
      if (!el) {
        const res = await runTool("list_areas", {});
        const areas = res.areas || [];
        const items = areas.map((a) => {
          const it = new vscode.TreeItem(
            a.name || a.id,
            vscode.TreeItemCollapsibleState.Collapsed
          );
          it.contextValue = "area";
          it.id = `area:${a.id}`;
          it.iconPath = new vscode.ThemeIcon("location");
          it.areaId = a.id;
          return it;
        });
        const all = new vscode.TreeItem("全部实体", vscode.TreeItemCollapsibleState.Collapsed);
        all.areaId = "*";
        all.iconPath = new vscode.ThemeIcon("list-tree");
        items.push(all);
        return items;
      }
      let entities;
      if (el.areaId === "*") {
        const res = await runTool("query_entities", { limit: 500 });
        entities = res.entities || [];
      } else {
        const res = await runTool("describe_area", { identifier: el.areaId });
        entities = res.entities || [];
      }
      const out = [];
      for (const ent of entities.slice(0, 200)) {
        const id = ent.entity_id || String(ent);
        const st = ent.state !== undefined ? ent : await this._stateOf(id);
        const state = st && st.state !== undefined ? ` · ${st.state}` : "";
        const name = ent.friendly_name || ent.name || (st && st.friendly_name) || id;
        const it = new vscode.TreeItem(`${name}${state}`);
        it.id = `ent:${el.areaId}:${id}`;
        it.tooltip = id;
        it.entityId = id;
        const domain = id.split(".")[0];
        it.iconPath = new vscode.ThemeIcon(
          { light: "lightbulb", switch: "plug", sensor: "pulse", climate: "flame" }[domain] ||
            "circle-outline"
        );
        if (["light", "switch", "input_boolean", "fan", "media_player", "cover"].includes(domain)) {
          it.command = {
            command: "haCopilot.toggleEntity",
            title: "toggle",
            arguments: [id],
          };
        }
        out.push(it);
      }
      return out;
    } catch (e) {
      const item = new vscode.TreeItem(`加载失败：${e.message.slice(0, 80)}`);
      return el ? [] : [item];
    }
  }
}

async function cmdToggleEntity(entityId) {
  if (!entityId) return;
  try {
    await runTool("control_entities", { entity_id: entityId, service: "toggle" });
  } catch {
    await api("POST", "/api/services/homeassistant/toggle", { entity_id: entityId });
  }
  setTimeout(() => homeProvider.refresh(), 600);
}

// ----------------------------------------------------------------- run tool --

async function cmdRunTool() {
  try {
    const cat = await api("GET", "/api/ha_copilot/tools");
    const tools = cat.tools || [];
    const pick = await vscode.window.showQuickPick(
      tools.map((t) => ({ label: t.name, description: (t.description || "").slice(0, 90) })),
      { placeHolder: "选择要运行的 ha_copilot 工具" }
    );
    if (!pick) return;
    const argsRaw = await vscode.window.showInputBox({
      prompt: `${pick.label} 参数 (JSON)`,
      value: "{}",
      ignoreFocusOut: true,
    });
    if (argsRaw === undefined) return;
    const result = await runTool(pick.label, JSON.parse(argsRaw || "{}"));
    const doc = await vscode.workspace.openTextDocument({
      language: "json",
      content: JSON.stringify(result, null, 2),
    });
    vscode.window.showTextDocument(doc, { preview: true });
  } catch (e) {
    vscode.window.showErrorMessage(`run_tool 失败：${e.message}`);
  }
}

// -------------------------------------------------------------- MCP config --

async function cmdMcpConfig() {
  const base = baseUrl();
  const tok = await token();
  if (!base || !tok) return vscode.window.showErrorMessage("先连接 Home Assistant。");
  const snippet = {
    mcpServers: {
      "ha-copilot": {
        url: `${base}/api/ha_copilot/mcp/sse`,
        transport: "sse",
        headers: { Authorization: `Bearer ${tok}` },
      },
    },
  };
  const doc = await vscode.workspace.openTextDocument({
    language: "json",
    content: JSON.stringify(snippet, null, 2),
  });
  vscode.window.showTextDocument(doc, { preview: true });
  vscode.window.showInformationMessage(
    "MCP 配置已生成 — 粘贴到 Claude Desktop / Cline / Cursor 的 MCP 配置中即可。"
  );
}

// ------------------------------------------------------------- chat webview --

const CHAT_STORE = "haCopilot.chatStore";

class ChatViewProvider {
  constructor() {
    /** @type {vscode.WebviewView | undefined} */
    this.view = undefined;
  }

  async pushConnection() {
    if (!this.view) return;
    this.view.webview.postMessage({
      type: "connection",
      baseUrl: baseUrl(),
      token: await token(),
      language: CFG().get("language") || "zh-CN",
      cloud: cloudCfg(),
      rules: rulesCfg(),
    });
  }

  newChat() {
    this.view?.webview.postMessage({ type: "newChat" });
  }

  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = chatHtml();
    view.webview.onDidReceiveMessage(async (msg) => {
      if (msg.type === "ready") {
        view.webview.postMessage({ type: "store", store: ctx.globalState.get(CHAT_STORE) || null });
        this.pushConnection();
      } else if (msg.type === "persist") ctx.globalState.update(CHAT_STORE, msg.store);
      else if (msg.type === "copied") vscode.env.clipboard.writeText(msg.text);
      else if (msg.type === "connect") vscode.commands.executeCommand("haCopilot.connect");
      else if (msg.type === "openPanel") vscode.commands.executeCommand("haCopilot.openPanel");
      else if (msg.type === "setProvider") { await setActiveProvider(msg.name); this.pushConnection(); }
      else if (msg.type === "error") vscode.window.showErrorMessage(`HA Copilot 对话：${msg.text}`);
    });
  }
}

function chatHtml() {
  // Copilot-style chat UI. The webview owns the HA WebSocket connection:
  // auth → subscribe ha_copilot_turn → conversation/process, streaming
  // deltas + tool cards, abort via ha_copilot/abort_turn.
  return /* html */ `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy"
  content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src http: https: ws: wss:;" />
<style>
  :root { color-scheme: light dark; }
  body { margin:0; font-family: var(--vscode-font-family); color: var(--vscode-foreground);
         background: var(--vscode-sideBar-background); display:flex; flex-direction:column; height:100vh; }
  #log { flex:1; overflow-y:auto; padding:8px; }
  .msg { margin:6px 0; padding:8px 10px; border-radius:8px; white-space:pre-wrap; word-break:break-word;
         font-size: var(--vscode-font-size); line-height:1.45; }
  .user { background: var(--vscode-input-background); border:1px solid var(--vscode-input-border, transparent); }
  .assistant { background: var(--vscode-editor-inactiveSelectionBackground); }
  .meta { opacity:.65; font-size:.85em; margin:2px 2px; }
  .tool { border:1px solid var(--vscode-widget-border, #8884); border-radius:6px; margin:4px 0;
          font-size:.85em; overflow:hidden; }
  .tool summary { cursor:pointer; padding:4px 8px; background: var(--vscode-editorWidget-background); }
  .tool pre { margin:0; padding:6px 8px; overflow-x:auto; max-height:160px; }
  .caret::after { content:"▍"; animation: blink 1s step-start infinite; }
  @keyframes blink { 50% { opacity:0; } }
  #bar { display:flex; gap:6px; padding:8px; border-top:1px solid var(--vscode-widget-border,#8884); }
  textarea { flex:1; resize:none; background: var(--vscode-input-background); color: var(--vscode-input-foreground);
             border:1px solid var(--vscode-input-border,transparent); border-radius:6px; padding:6px 8px;
             font-family:inherit; font-size:inherit; min-height:34px; max-height:120px; }
  button { background: var(--vscode-button-background); color: var(--vscode-button-foreground);
           border:0; border-radius:6px; padding:0 12px; cursor:pointer; }
  button.secondary { background: var(--vscode-button-secondaryBackground);
                     color: var(--vscode-button-secondaryForeground); }
  #status { padding:4px 10px; font-size:.85em; opacity:.8; display:flex; align-items:center; gap:6px; }
  .dot { width:8px; height:8px; border-radius:50%; background:#d33; display:inline-block; flex:none; }
  .dot.on { background:#3c3; }
  a { color: var(--vscode-textLink-foreground); cursor:pointer; }
  #sessbar { display:flex; gap:4px; padding:4px 8px; align-items:center;
             border-bottom:1px solid var(--vscode-widget-border,#8884); }
  #sess { flex:1; min-width:0; background: var(--vscode-dropdown-background);
          color: var(--vscode-dropdown-foreground); border:1px solid var(--vscode-dropdown-border,#8884);
          border-radius:4px; padding:2px 4px; font-size:.85em; }
  .iconbtn { background:transparent; color:var(--vscode-foreground); border:1px solid transparent;
             border-radius:4px; padding:2px 7px; cursor:pointer; font-size:.95em; }
  .iconbtn:hover { background: var(--vscode-toolbar-hoverBackground,#8883); }
  .msg.assistant code { background: var(--vscode-textCodeBlock-background,#0003); border-radius:3px;
                        padding:0 3px; font-family: var(--vscode-editor-font-family); }
  .msg.assistant pre { background: var(--vscode-textCodeBlock-background,#0003); border-radius:6px;
                       padding:6px 8px; overflow-x:auto; white-space:pre; }
  .msg.assistant p { margin:.3em 0; }
  .msg.assistant pre { cursor:pointer; }
  .msg.assistant pre:hover { outline:1px solid var(--vscode-focusBorder,#0af8); }
  .msg.assistant h1, .msg.assistant h2, .msg.assistant h3 { margin:.4em 0 .2em; line-height:1.25; }
  .msg.assistant h1 { font-size:1.25em; } .msg.assistant h2 { font-size:1.15em; }
  .msg.assistant h3 { font-size:1.05em; }
  .msg.assistant ul, .msg.assistant ol { margin:.3em 0; padding-left:1.4em; }
  .msg.assistant li { margin:.15em 0; }
  .msg.assistant blockquote { margin:.3em 0; padding:2px 10px;
                              border-left:3px solid var(--vscode-widget-border,#8884); opacity:.9; }
  .msg.assistant hr { border:0; border-top:1px solid var(--vscode-widget-border,#8884); margin:.5em 0; }
  .tool.running summary { opacity:.85; }
  .spin { display:inline-block; width:9px; height:9px; margin-right:5px; flex:none;
          border:2px solid var(--vscode-foreground); border-top-color:transparent; border-radius:50%;
          vertical-align:-1px; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  #chips { display:flex; gap:4px; padding:4px 8px; flex-wrap:wrap; }
  .chip { font-size:.8em; border:1px solid var(--vscode-widget-border,#8884); border-radius:10px;
          padding:2px 8px; cursor:pointer; opacity:.85; }
  .chip:hover { background: var(--vscode-toolbar-hoverBackground,#8883); opacity:1; }
  #toast { position:fixed; bottom:56px; left:50%; transform:translateX(-50%);
           background: var(--vscode-editorWidget-background); border:1px solid var(--vscode-widget-border,#8884);
           border-radius:6px; padding:3px 10px; font-size:.85em; display:none; }
  #console { display:none; flex-direction:column; gap:6px; padding:8px; max-height:46vh; overflow-y:auto;
             border-bottom:1px solid var(--vscode-widget-border,#8884);
             background: var(--vscode-editorWidget-background); }
  #console.open { display:flex; }
  #console > * { flex-shrink:0; }
  #console input, #console select { background: var(--vscode-input-background);
             color: var(--vscode-input-foreground); border:1px solid var(--vscode-input-border,#8884);
             border-radius:4px; padding:3px 6px; font-size:.85em; }
  #targs { resize:vertical; min-height:52px; max-height:160px; background: var(--vscode-input-background);
           color: var(--vscode-input-foreground); border:1px solid var(--vscode-input-border,#8884);
           border-radius:4px; padding:4px 6px; font-size:.82em;
           font-family: var(--vscode-editor-font-family, monospace); }
  .tdesc { font-size:.78em; opacity:.75; line-height:1.35; min-height:12px;
           max-height:72px; overflow-y:auto; }
  .op { border:1px solid var(--vscode-widget-border,#8884); border-radius:5px; margin:2px 0;
        font-size:.8em; overflow:hidden; }
  .op-call { padding:3px 6px; background: var(--vscode-editorWidget-background); word-break:break-all; }
  .op-res { padding:3px 6px; white-space:pre-wrap; word-break:break-all; max-height:110px; overflow-y:auto;
            font-family: var(--vscode-editor-font-family, monospace); }
  .op-res.ok { color: var(--vscode-testing-iconPassed, #3c3); }
  .op-res.err { color: var(--vscode-errorForeground, #d33); }
</style>
</head>
<body>
<div id="status"><span class="dot" id="dot"></span><span id="stext">未连接</span>
  <select id="prov" title="云端渠道" style="margin-left:auto;display:none;max-width:130px;background:var(--vscode-dropdown-background);color:var(--vscode-dropdown-foreground);border:1px solid var(--vscode-dropdown-border,#8884);border-radius:4px;font-size:.85em"></select>
  <a id="connectLink">连接…</a></div>
<div id="sessbar">
  <select id="sess" title="会话"></select>
  <button class="iconbtn" id="newSess" title="新建会话">＋</button>
  <button class="iconbtn" id="delSess" title="删除当前会话">🗑</button>
  <button class="iconbtn" id="consoleBtn" title="命令台：直连 ha_copilot 工具层（无模型，确定性执行）">☰</button>
  <button class="iconbtn" id="agentBtn" title="本源代理：外接模型自主调度 HA 工具层（搜资料/读写配置/执行工具 全链路）">⚡</button>
</div>
<div id="console">
  <input id="tfilter" placeholder="搜索工具（名称/描述）…" />
  <select id="tsel"></select>
  <div class="tdesc" id="tdesc"></div>
  <textarea id="targs" placeholder='参数 JSON，例如 {"domain":"light"}'></textarea>
  <div style="display:flex;gap:6px;align-items:center">
    <button id="trun">执行工具</button>
    <button id="tclear" class="secondary" title="清空记录">⟲</button>
    <span class="tdesc" id="tcount" style="margin-left:auto"></span>
  </div>
  <div id="oplog"></div>
</div>
<div id="log"></div>
<div id="toast">已复制</div>
<div id="chips">
  <span class="chip" data-t="帮我设计一条自动化：">⚙ 设计自动化</span>
  <span class="chip" data-t="搜索社区蓝图并推荐导入：">📐 搜社区蓝图</span>
  <span class="chip" data-t="体检所有集成健康度并修复异常">🩺 集成体检</span>
  <span class="chip" data-t="帮我设计/优化仪表盘：">🖼 设计仪表盘</span>
  <span class="chip" data-t="审计全部自动化，找出失效/冲突/可优化项">🔍 审计自动化</span>
</div>
<div id="bar">
  <textarea id="input" placeholder="让 Copilot 代你操作 Home Assistant 系统本身：设计自动化、配置集成、搜社区蓝图、设计仪表盘…（Enter 发送）"></textarea>
  <button id="send">发送</button>
  <button id="stop" class="secondary" style="display:none">■ 停止</button>
</div>
<script>
const vscodeApi = acquireVsCodeApi();
let conn = { baseUrl: "", token: "", language: "zh-CN" };
let ws = null, wsId = 0, pending = {}, subId = 0, authed = false;
let convId = null, busy = false, curBubble = null, curText = "";
let cloud = null, aborter = null, rules = null, pendingTools = [];
const provSel = document.getElementById("prov");
provSel.onchange = () => vscodeApi.postMessage({ type: "setProvider", name: provSel.value });
function renderProviders() {
  const list = (cloud && cloud.providers) || [];
  provSel.style.display = list.length ? "" : "none";
  provSel.innerHTML = "";
  for (const p of list) {
    const o = document.createElement("option");
    o.value = p.name; o.textContent = p.name + (p.model ? " · " + p.model : "");
    if (cloud && p.name === cloud.activeName) o.selected = true;
    provSel.appendChild(o);
  }
}

// -------- multi-session store (persisted in extension globalState) --------
let store = { sessions: [], cur: null, consoleOpen: false, oplog: [] };
const sessSel = document.getElementById("sess");

function curSess() { return store.sessions.find((s) => s.id === store.cur); }
function persist() { vscodeApi.postMessage({ type: "persist", store }); }
function newSession() {
  const s = { id: String(Date.now()), title: "新会话", convId: null, msgs: [] };
  store.sessions.unshift(s); store.cur = s.id;
  convId = null; renderSessions(); renderAll(); persist();
}
function renderSessions() {
  sessSel.innerHTML = "";
  for (const s of store.sessions) {
    const o = document.createElement("option");
    o.value = s.id; o.textContent = s.title;
    if (s.id === store.cur) o.selected = true;
    sessSel.appendChild(o);
  }
}
function pushMsg(m) {
  const s = curSess(); if (!s) return;
  s.msgs.push(m);
  if (m.role === "user" && s.title === "新会话") {
    s.title = m.text.slice(0, 24) || "新会话"; renderSessions();
  }
  persist();
}

// -------- minimal markdown renderer for assistant messages --------
function esc(t) { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function inlineMd(s) {
  return s
    .replace(/\`([^\`\\n]+)\`/g, "<code>$1</code>")
    .replace(/\\*\\*([^*\\n]+)\\*\\*/g, "<b>$1</b>")
    .replace(/\\[([^\\]\\n]+)\\]\\((https?:[^)\\s]+)\\)/g, '<a href="$2">$1</a>');
}
function md(text) {
  const blocks = [];
  const t = esc(text).replace(/\`\`\`([\\s\\S]*?)\`\`\`/g, (m, c) => {
    blocks.push("<pre>" + c.replace(/^\\w*\\n/, "") + "</pre>");
    return "\\u0000" + (blocks.length - 1) + "\\u0000";
  });
  const out = []; let list = null;
  const flush = () => {
    if (list) { out.push("<" + list.tag + ">" + list.items.join("") + "</" + list.tag + ">"); list = null; }
  };
  for (const ln of t.split("\\n")) {
    let mm;
    if (/^\\s*\\u0000\\d+\\u0000\\s*$/.test(ln)) { flush(); out.push(ln.trim()); }
    else if ((mm = ln.match(/^(#{1,3})\\s+(.*)$/)))
      { flush(); out.push("<h" + mm[1].length + ">" + inlineMd(mm[2]) + "</h" + mm[1].length + ">"); }
    else if (/^\\s*(---+|\\*\\*\\*+)\\s*$/.test(ln)) { flush(); out.push("<hr>"); }
    else if ((mm = ln.match(/^\\s*&gt;\\s?(.*)$/)))
      { flush(); out.push("<blockquote>" + inlineMd(mm[1]) + "</blockquote>"); }
    else if ((mm = ln.match(/^\\s*[-*]\\s+(.*)$/))) {
      if (!list || list.tag !== "ul") { flush(); list = { tag: "ul", items: [] }; }
      list.items.push("<li>" + inlineMd(mm[1]) + "</li>");
    } else if ((mm = ln.match(/^\\s*\\d+\\.\\s+(.*)$/))) {
      if (!list || list.tag !== "ol") { flush(); list = { tag: "ol", items: [] }; }
      list.items.push("<li>" + inlineMd(mm[1]) + "</li>");
    } else if (ln.trim() === "") flush();
    else { flush(); out.push("<p>" + inlineMd(ln) + "</p>"); }
  }
  flush();
  return out.join("").replace(/\\u0000(\\d+)\\u0000/g, (m, i) => blocks[+i]);
}

function renderMsg(m) {
  if (m.role === "user") { log.appendChild(el("div", "msg user", m.text)); }
  else if (m.role === "assistant") {
    const b = el("div", "msg assistant"); b.innerHTML = md(m.text); log.appendChild(b);
  } else if (m.role === "meta") { log.appendChild(el("div", "meta", m.text)); }
  else if (m.role === "tool") {
    const card = document.createElement("details"); card.className = "tool";
    const s = document.createElement("summary");
    s.textContent = "🛠 " + (m.name || "tool") + (m.ms !== undefined ? " · " + m.ms + "ms" : "");
    card.appendChild(s);
    card.appendChild(el("pre", "", (m.result || "").slice(0, 4000)));
    log.appendChild(card);
  }
}
function renderAll() {
  log.innerHTML = ""; curBubble = null; curText = ""; pendingTools = [];
  const s = curSess();
  if (s) { for (const m of s.msgs) renderMsg(m); convId = s.convId || null; }
  scroll();
}

sessSel.onchange = () => { store.cur = sessSel.value; renderAll(); persist(); };
document.getElementById("newSess").onclick = () => newSession();
document.getElementById("delSess").onclick = () => {
  store.sessions = store.sessions.filter((s) => s.id !== store.cur);
  store.cur = store.sessions[0]?.id || null;
  if (!store.cur) return newSession();
  renderSessions(); renderAll(); persist();
};

const log = document.getElementById("log");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const stopBtn = document.getElementById("stop");
const dot = document.getElementById("dot");
const stext = document.getElementById("stext");
document.getElementById("connectLink").onclick = () => vscodeApi.postMessage({ type: "connect" });

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function scroll() { log.scrollTop = log.scrollHeight; }
let toastT = 0;
log.addEventListener("click", (e) => {
  const pre = e.target.closest("pre");
  if (!pre || !pre.closest(".msg.assistant")) return;
  navigator.clipboard.writeText(pre.textContent).then(() => {
    const t = document.getElementById("toast");
    t.style.display = "block"; clearTimeout(toastT);
    toastT = setTimeout(() => { t.style.display = "none"; }, 1200);
  });
});
function setBusy(b) {
  busy = b;
  stopBtn.style.display = b ? "" : "none";
  sendBtn.disabled = b;
}

function wsSend(msg) {
  return new Promise((resolve, reject) => {
    msg.id = ++wsId;
    pending[msg.id] = { resolve, reject };
    ws.send(JSON.stringify(msg));
  });
}

function connect() {
  if (ws) { try { ws.close(); } catch {} ws = null; }
  authed = false;
  if (!conn.baseUrl || !conn.token) {
    if (cloud && cloud.baseUrl && cloud.apiKey) {
      dot.className = "dot on"; stext.textContent = "云端直连 · " + (cloud.activeName || cloud.model);
    } else { dot.className = "dot"; stext.textContent = "未连接"; }
    return;
  }
  const wsUrl = conn.baseUrl.replace(/^http/, "ws") + "/api/websocket";
  try { ws = new WebSocket(wsUrl); } catch (e) { stext.textContent = "WS 失败: " + e.message; return; }
  stext.textContent = "连接中…";
  ws.onmessage = async (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "auth_required") ws.send(JSON.stringify({ type: "auth", access_token: conn.token }));
    else if (m.type === "auth_ok") {
      authed = true; wsId = 0; pending = {};
      dot.className = "dot on";
      stext.textContent = conn.baseUrl.replace(/^https?:\\/\\//, "");
      const sub = await wsSend({ type: "subscribe_events", event_type: "ha_copilot_turn" });
      subId = wsId;
    } else if (m.type === "auth_invalid") { dot.className = "dot"; stext.textContent = "令牌无效"; }
    else if (m.type === "result" && pending[m.id]) {
      const p = pending[m.id]; delete pending[m.id];
      m.success ? p.resolve(m.result) : p.reject(new Error((m.error && m.error.message) || "ws error"));
    } else if (m.type === "event" && m.event && m.event.event_type === "ha_copilot_turn") {
      onTurn(m.event.data || {});
    }
  };
  ws.onclose = () => { dot.className = "dot"; if (authed) stext.textContent = "连接已断开 — 重试中…";
                       setTimeout(connect, 3000); };
  ws.onerror = () => {};
}

function closeBubble() {
  if (curBubble && curText) {
    curBubble.classList.remove("caret");
    curBubble.innerHTML = md(curText);
    pushMsg({ role: "assistant", text: curText });
  } else if (curBubble) curBubble.classList.remove("caret");
  curBubble = null; curText = "";
}

function makeToolCard(name) {
  const card = document.createElement("details"); card.className = "tool running";
  const s = document.createElement("summary");
  s.innerHTML = '<span class="spin"></span>\ud83d\udee0 ' + esc(String(name || "tool")) + " · 运行中…";
  card.appendChild(s);
  const pre = el("pre", "", "");
  card.appendChild(pre);
  log.appendChild(card); scroll();
  return { name, card, summary: s, pre, done: false };
}

function onTurn(d) {
  // Server may allocate a fresh conversation_id (e.g. history expired). While a
  // turn is in flight, adopt whatever id the stream carries instead of dropping
  // its events; only filter cross-conversation events when idle.
  if (convId && d.conversation_id && d.conversation_id !== convId && !busy) return;
  if (d.conversation_id) {
    convId = d.conversation_id;
    const s = curSess(); if (s) s.convId = convId;
  }
  if (d.phase === "delta") {
    if (!curBubble) { curBubble = el("div", "msg assistant caret"); log.appendChild(curBubble); }
    curText += d.delta || d.text || "";
    curBubble.textContent = curText;
    scroll();
  } else if (d.phase === "round") {
    closeBubble();
    const calls = d.tool_calls || [];
    if (calls.length) {
      const text = "⚙ 第 " + ((d.iteration ?? 0) + 1) + " 轮 · " + (d.llm_ms ?? "?") + "ms";
      log.appendChild(el("div", "meta", text)); scroll();
      pushMsg({ role: "meta", text });
      for (const c of calls) pendingTools.push(makeToolCard(c.name));
    }
  } else if (d.phase === "tool_result") {
    const resStr = JSON.stringify(d.result, null, 2) || "";
    let slot = pendingTools.find((p) => !p.done && p.name === d.name) ||
               pendingTools.find((p) => !p.done);
    if (slot) {
      slot.done = true;
      slot.card.classList.remove("running");
      slot.summary.textContent = "\ud83d\udee0 " + (d.name || "tool") +
                                 (d.ms !== undefined ? " · " + d.ms + "ms" : "");
      slot.pre.textContent = resStr.slice(0, 4000);
    } else renderMsg({ role: "tool", name: d.name, ms: d.ms, result: resStr });
    scroll();
    pushMsg({ role: "tool", name: d.name, ms: d.ms, result: resStr });
  } else if (d.phase === "final") {
    closeBubble();
    pendingTools = [];
    setBusy(false);
  }
}

async function cloudSend() {
  setBusy(true);
  curBubble = el("div", "msg assistant caret"); log.appendChild(curBubble); curText = "";
  const s = curSess();
  const hist = (s ? s.msgs : [])
    .filter((m) => m.role === "user" || m.role === "assistant")
    .slice(-20)
    .map((m) => ({ role: m.role, content: m.text }));
  aborter = new AbortController();
  try {
    const res = await fetch(cloud.baseUrl + "/chat/completions", {
      method: "POST",
      signal: aborter.signal,
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + cloud.apiKey },
      body: JSON.stringify({
        model: cloud.model,
        stream: true,
        messages: [
          { role: "system",
            content: (rules && rules.prompt) ||
              "你是 HA Copilot，VS Code 里的智能生态助手：擅长智能家居系统设计与开发解答。用中文简洁回答。" },
          ...hist,
        ],
      }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status + " " + (await res.text()).slice(0, 200));
    const rd = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { done, value } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\\n")) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (data === "[DONE]") continue;
        try {
          const j = JSON.parse(data);
          const d = (j.choices && j.choices[0] && j.choices[0].delta && j.choices[0].delta.content) || "";
          if (d) { curText += d; curBubble.textContent = curText; scroll(); }
        } catch {}
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") {
      curText += (curText ? "\\n" : "") + "⚠ " + e.message;
      curBubble.textContent = curText;
    }
  } finally { aborter = null; closeBubble(); setBusy(false); }
}

// -------- 本源代理：Devin Desktop 式工具层（网络资料/文件/执行 三层照搬，全部归化为 HA 板块） --------
// 外接模型（OpenAI 兼容 tool-calling）自主调度；工具执行经 WS ha_copilot/run_tool
// 深层直连（HTTP 兜底），与命令台/MCP 同一工具层。
const AGENT_SEARCH_MAP = {
  all: "discover_resources", hacs: "search_community_resources", github: "search_github",
  blueprints: "search_blueprints", zigbee: "search_zigbee_devices", zwave: "search_zwave_devices",
  tasmota: "search_tasmota_devices", esphome: "search_esphome_devices",
  integrations: "search_ha_integrations", addons: "search_ha_addons",
};
const AGENT_TOOLS = [
  { name: "search_web",
    desc: "联网搜索 Home Assistant 生态资料（九源：HACS/社区蓝图/GitHub/Zigbee/Z-Wave/Tasmota/ESPHome/官方集成/加载项）",
    params: { type: "object", properties: {
      query: { type: "string", description: "搜索词" },
      source: { type: "string", enum: Object.keys(AGENT_SEARCH_MAP), description: "资料源，默认 all=九源聚合" },
      limit: { type: "integer" } }, required: ["query"] } },
  { name: "search_tools", desc: "按意图在 2100+ 确定性 HA 工具目录中检索最相关工具",
    params: { type: "object", properties: { query: { type: "string" }, limit: { type: "integer" } }, required: ["query"] } },
  { name: "describe_tool", desc: "查看某个工具的完整参数 schema",
    params: { type: "object", properties: { name: { type: "string" } }, required: ["name"] } },
  { name: "run_tool", desc: "执行工具目录中的任意工具（先 search_tools 找名，再 describe_tool 看参）",
    params: { type: "object", properties: { tool: { type: "string" }, args: { type: "object", description: "工具参数对象" } }, required: ["tool"] } },
  { name: "list_dir", desc: "列出 HA 配置目录内容",
    params: { type: "object", properties: { path: { type: "string", description: "相对 config 根，空=根目录" } } } },
  { name: "read_file", desc: "读取 HA 配置文件内容",
    params: { type: "object", properties: { path: { type: "string" } }, required: ["path"] } },
  { name: "write_file", desc: "写入（新建/整文件覆盖）HA 配置文件，自动留 .copilot.bak 备份",
    params: { type: "object", properties: { path: { type: "string" }, content: { type: "string" } }, required: ["path", "content"] } },
  { name: "edit_file", desc: "对既有配置文件做精准字符串替换（最小必要变更；old_str 必须在文件中唯一）",
    params: { type: "object", properties: { path: { type: "string" }, old_str: { type: "string" }, new_str: { type: "string" } },
      required: ["path", "old_str", "new_str"] } },
  { name: "render_template", desc: "执行 Jinja2 模板（计算/查询实时状态）",
    params: { type: "object", properties: { template: { type: "string" } }, required: ["template"] } },
  { name: "check_config", desc: "校验整个 HA 配置合法性", params: { type: "object", properties: {} } },
  { name: "get_logs", desc: "读取系统错误/警告日志", params: { type: "object", properties: {} } },
  { name: "call_service", desc: "直接调用任意 HA 服务",
    params: { type: "object", properties: { domain: { type: "string" }, service: { type: "string" }, data: { type: "object" } },
      required: ["domain", "service"] } },
];
function agentToolSpecs() {
  return AGENT_TOOLS.map((t) => ({ type: "function", function: { name: t.name, description: t.desc, parameters: t.params } }));
}
async function haTool(tool, args) {
  if (authed) return wsSend({ type: "ha_copilot/run_tool", tool, args: args || {} });
  if (conn.baseUrl && conn.token) {
    const res = await fetch(conn.baseUrl + "/api/ha_copilot/run_tool", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + conn.token },
      body: JSON.stringify({ tool, args: args || {} }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return (await res.json()).result;
  }
  return { error: "未连接 Home Assistant，工具层不可用——请先连接 HA 或仅作纯对话回答" };
}
async function execAgentTool(name, args) {
  args = args || {};
  if (name === "search_web") {
    const src = AGENT_SEARCH_MAP[args.source] || "discover_resources";
    return haTool(src, { query: args.query, limit: args.limit || 6 });
  }
  if (name === "search_tools") return haTool("search_tools", { query: args.query, limit: args.limit || 15 });
  if (name === "describe_tool") return haTool("describe_tool", { name: args.name });
  if (name === "run_tool") {
    let a = args.args;
    if (typeof a === "string") { try { a = JSON.parse(a); } catch { a = {}; } }
    return haTool(args.tool, a || {});
  }
  if (name === "list_dir") return haTool("list_dir", { path: args.path || "" });
  if (name === "read_file") return haTool("read_config_file", { path: args.path });
  if (name === "write_file") return haTool("write_config_file", { path: args.path, content: args.content });
  if (name === "edit_file") {
    const r = await haTool("read_config_file", { path: args.path });
    if (!r || r.error) return r || { error: "读取失败" };
    const txt = String(r.content ?? "");
    const hits = txt.split(args.old_str).length - 1;
    if (hits === 0) return { error: "old_str 在文件中未找到，未做任何修改" };
    if (hits > 1) return { error: "old_str 在文件中出现 " + hits + " 次（必须唯一），请带更多上下文重试" };
    return haTool("write_config_file", { path: args.path, content: txt.replace(args.old_str, args.new_str) });
  }
  if (name === "render_template") return haTool("render_template", { template: args.template });
  if (name === "check_config") return haTool("check_config", {});
  if (name === "get_logs") return haTool("system_log_list", {});
  if (name === "call_service")
    return haTool("call_service", { domain: args.domain, service: args.service, data: args.data || {} });
  return { error: "未知工具 " + name };
}

async function agentSend() {
  setBusy(true);
  const s = curSess();
  const hist = (s ? s.msgs : [])
    .filter((m) => m.role === "user" || m.role === "assistant")
    .slice(-20)
    .map((m) => ({ role: m.role, content: m.text }));
  const msgs = [
    { role: "system",
      content: (rules && (rules.agentPrompt || rules.prompt)) ||
        "你是 HA Copilot，IDE 里的智能家居生态操作员。道法自然，先观后动，用中文简洁回答。" },
    ...hist,
  ];
  aborter = new AbortController();
  curBubble = null; curText = "";
  try {
    for (let iter = 0; iter < 12; iter++) {
      const t0 = Date.now();
      const res = await fetch(cloud.baseUrl + "/chat/completions", {
        method: "POST",
        signal: aborter.signal,
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + cloud.apiKey },
        body: JSON.stringify({ model: cloud.model, stream: true, messages: msgs,
                               tools: agentToolSpecs(), tool_choice: "auto" }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status + " " + (await res.text()).slice(0, 200));
      const rd = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
      let content = "", calls = [];
      for (;;) {
        const { done, value } = await rd.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\\n")) >= 0) {
          const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (data === "[DONE]") continue;
          let j; try { j = JSON.parse(data); } catch { continue; }
          const delta = (j.choices && j.choices[0] && j.choices[0].delta) || {};
          if (delta.content) {
            content += delta.content;
            if (!curBubble) { curBubble = el("div", "msg assistant caret"); log.appendChild(curBubble); }
            curText = content; curBubble.textContent = curText; scroll();
          }
          for (const tc of delta.tool_calls || []) {
            const k = tc.index ?? 0;
            calls[k] = calls[k] || { id: "", name: "", args: "" };
            if (tc.id) calls[k].id = tc.id;
            if (tc.function && tc.function.name) calls[k].name += tc.function.name;
            if (tc.function && tc.function.arguments) calls[k].args += tc.function.arguments;
          }
        }
      }
      closeBubble();
      calls = calls.filter(Boolean);
      if (!calls.length) return;
      const meta = "⚙ 第 " + (iter + 1) + " 轮 · " + (Date.now() - t0) + "ms";
      log.appendChild(el("div", "meta", meta)); scroll();
      pushMsg({ role: "meta", text: meta });
      msgs.push({ role: "assistant", content: content || null,
                  tool_calls: calls.map((c) => ({ id: c.id, type: "function",
                    function: { name: c.name, arguments: c.args || "{}" } })) });
      for (const c of calls) {
        const slot = makeToolCard(c.name);
        let parsed = {}; try { parsed = JSON.parse(c.args || "{}"); } catch {}
        const tt0 = Date.now();
        let result;
        try { result = await execAgentTool(c.name, parsed); }
        catch (e) { result = { error: e.message }; }
        const ms = Date.now() - tt0;
        const resStr = JSON.stringify(result, null, 2) || "";
        slot.done = true;
        slot.card.classList.remove("running");
        slot.summary.textContent = "\ud83d\udee0 " + c.name + " · " + ms + "ms";
        slot.pre.textContent = resStr.slice(0, 4000);
        scroll();
        pushMsg({ role: "tool", name: c.name, ms, result: resStr });
        msgs.push({ role: "tool", tool_call_id: c.id, content: resStr.slice(0, 12000) });
      }
      if (aborter.signal.aborted) return;
    }
  } catch (e) {
    if (e.name !== "AbortError") {
      if (!curBubble) { curBubble = el("div", "msg assistant"); log.appendChild(curBubble); }
      curText += (curText ? "\\n" : "") + "⚠ " + e.message;
      curBubble.textContent = curText;
      closeBubble();
    }
  } finally { aborter = null; closeBubble(); setBusy(false); }
}

async function send() {
  const text = input.value.trim();
  if (!text || busy) return;
  const cloudReady = cloud && cloud.baseUrl && cloud.apiKey;
  if (!authed && !cloudReady) { vscodeApi.postMessage({ type: "connect" }); return; }
  input.value = ""; autoGrow();
  pendingTools = [];
  if (!curSess()) newSession();
  log.appendChild(el("div", "msg user", text)); scroll();
  pushMsg({ role: "user", text });
  if (cloudReady && store.agentOn !== false) return agentSend();
  if (!authed) return cloudSend();
  setBusy(true); curBubble = null; curText = "";
  try {
    const msg = { type: "conversation/process", text, language: conn.language,
                  agent_id: "conversation.ha_copilot" };
    if (convId) msg.conversation_id = convId;
    const res = await wsSend(msg);
    convId = (res && res.conversation_id) || convId;
    const speech = res && res.response && res.response.speech &&
                   res.response.speech.plain && res.response.speech.plain.speech;
    // If streaming produced no bubble (older backend), show final speech.
    if (speech && !log.lastElementChild?.classList?.contains("assistant")) {
      log.appendChild(el("div", "msg assistant", speech)); scroll();
      pushMsg({ role: "assistant", text: speech });
    }
  } catch (e) {
    log.appendChild(el("div", "msg assistant", "⚠ " + e.message)); scroll();
  } finally { setBusy(false); closeBubble(); }
}

stopBtn.onclick = async () => {
  if (aborter) { aborter.abort(); return; }
  if (!convId || !authed) return;
  try { await wsSend({ type: "ha_copilot/abort_turn", conversation_id: convId }); } catch {}
};
for (const c of document.querySelectorAll("#chips .chip")) {
  c.onclick = () => { input.value = c.dataset.t; input.focus(); };
}
sendBtn.onclick = send;
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 120) + "px";
}
input.addEventListener("input", autoGrow);

// -------- 命令台：直连 ha_copilot 深层工具层（确定性执行 · 无模型） --------
// 与生态面板命令台同源：HTTP 目录（含 inputSchema）+ WS ha_copilot/run_tool 直连，
// HTTP run_tool 兜底 — 全程绕开官方 conversation/service 高层封装。
const consoleBox = document.getElementById("console");
const tfilter = document.getElementById("tfilter");
const tsel = document.getElementById("tsel");
const tdesc = document.getElementById("tdesc");
const targs = document.getElementById("targs");
const trun = document.getElementById("trun");
const oplogBox = document.getElementById("oplog");
let tools = [], lastPicked = null, consoleBusy = false;

document.getElementById("consoleBtn").onclick = () => {
  store.consoleOpen = !store.consoleOpen;
  applyConsoleOpen(); persist();
  if (store.consoleOpen && !tools.length) loadTools();
};
function applyConsoleOpen() { consoleBox.classList.toggle("open", !!store.consoleOpen); }

const agentBtn = document.getElementById("agentBtn");
function applyAgentBtn() {
  const on = store.agentOn !== false;
  agentBtn.style.opacity = on ? "1" : ".35";
  agentBtn.title = (on ? "本源代理已开" : "本源代理已关（纯对话）") +
    " · 外接模型自主调度 HA 工具层（搜资料/读写配置/执行工具 全链路）";
}
agentBtn.onclick = () => {
  store.agentOn = store.agentOn === false;
  applyAgentBtn(); persist();
};

async function loadTools() {
  if (!conn.baseUrl || !conn.token) return;
  try {
    const res = await fetch(conn.baseUrl + "/api/ha_copilot/tools", {
      headers: { Authorization: "Bearer " + conn.token },
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    tools = (await res.json()).tools || [];
  } catch (e) {
    try { tools = ((await wsSend({ type: "ha_copilot/tools", with_schema: true })) || {}).tools || []; } catch {}
  }
  renderTools();
}
function renderTools() {
  const q = (tfilter.value || "").trim().toLowerCase();
  const list = q
    ? tools.filter((t) => t.name.toLowerCase().includes(q) ||
                          (t.description || "").toLowerCase().includes(q))
    : tools;
  const prev = tsel.value;
  tsel.innerHTML = "";
  for (const t of list.slice(0, 400)) {
    const o = document.createElement("option");
    o.value = t.name; o.textContent = t.name;
    tsel.appendChild(o);
  }
  document.getElementById("tcount").textContent =
    list.length + " / " + tools.length + " 工具";
  if (prev && list.some((t) => t.name === prev)) tsel.value = prev;
  onToolPick();
}
function schemaSkeleton(props) {
  const out = {};
  for (const [k, spec] of Object.entries(props)) {
    const ty = (spec && spec.type) || "string";
    out[k] = ty === "boolean" ? false
           : ty === "integer" || ty === "number" ? 0
           : ty === "array" ? [] : ty === "object" ? {} : "";
  }
  return out;
}
function onToolPick() {
  const t = tools.find((x) => x.name === tsel.value);
  if (!t) { tdesc.textContent = ""; return; }
  const props = (t.inputSchema && t.inputSchema.properties) || {};
  const req = (t.inputSchema && t.inputSchema.required) || [];
  const names = Object.keys(props);
  let hint = t.description || "";
  if (names.length)
    hint += "  ·  参数: " + names.map((n) => (req.includes(n) ? n + "*" : n)).join(", ") + "（*必填）";
  tdesc.textContent = hint;
  if (lastPicked !== t.name) {
    lastPicked = t.name;
    targs.value = names.length ? JSON.stringify(schemaSkeleton(props), null, 2) : "";
  }
}
tfilter.addEventListener("input", renderTools);
tsel.onchange = onToolPick;

function appendOp(e) {
  const div = el("div", "op");
  const call = el("div", "op-call");
  call.textContent = e.tool + "(" + JSON.stringify(e.args) + ")";
  const res = el("div", "op-res " + (e.ok ? "ok" : "err"));
  res.textContent = (JSON.stringify(e.result, null, 1) || "").slice(0, 4000);
  div.appendChild(call); div.appendChild(res);
  oplogBox.appendChild(div); oplogBox.scrollTop = oplogBox.scrollHeight;
}
function renderOplog() {
  oplogBox.innerHTML = "";
  for (const e of store.oplog || []) appendOp(e);
}
async function runConsoleTool(tool, args) {
  if (authed) return wsSend({ type: "ha_copilot/run_tool", tool, args });
  const res = await fetch(conn.baseUrl + "/api/ha_copilot/run_tool", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + conn.token },
    body: JSON.stringify({ tool, args }),
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return (await res.json()).result;
}
trun.onclick = async () => {
  if (consoleBusy) return;
  const tool = tsel.value;
  if (!tool) return;
  let args = {};
  const raw = (targs.value || "").trim();
  if (raw) {
    try { args = JSON.parse(raw); }
    catch { appendOp({ tool, args: raw, result: { error: "参数不是合法 JSON" }, ok: false }); return; }
  }
  consoleBusy = true; trun.disabled = true;
  let entry;
  try {
    const result = await runConsoleTool(tool, args);
    const ok = !(result && typeof result === "object" && "error" in result);
    entry = { tool, args, result, ok, ts: Date.now() };
  } catch (e) {
    entry = { tool, args, result: { error: e.message }, ok: false, ts: Date.now() };
  }
  store.oplog = (store.oplog || []).concat(entry).slice(-50);
  appendOp(entry); persist();
  consoleBusy = false; trun.disabled = false;
};
document.getElementById("tclear").onclick = () => {
  store.oplog = []; renderOplog(); persist();
};

window.addEventListener("message", (ev) => {
  const m = ev.data;
  if (m.type === "connection") {
    conn = m; cloud = m.cloud || null; rules = m.rules || null; renderProviders(); connect();
    if (store.consoleOpen) loadTools();
  }
  else if (m.type === "newChat") { newSession(); setBusy(false); }
  else if (m.type === "store") {
    if (m.store && m.store.sessions && m.store.sessions.length) {
      store = m.store; renderSessions(); renderAll();
    } else newSession();
    if (!store.oplog) store.oplog = [];
    applyConsoleOpen(); applyAgentBtn(); renderOplog();
    if (store.consoleOpen && conn.baseUrl && !tools.length) loadTools();
  }
});
vscodeApi.postMessage({ type: "ready" });
</script>
</body>
</html>`;
}

async function cmdExportChat() {
  const store = ctx.globalState.get(CHAT_STORE);
  const sess = store?.sessions?.find((s) => s.id === store.cur) || store?.sessions?.[0];
  if (!sess || !sess.msgs.length) return vscode.window.showInformationMessage("当前没有可导出的会话。");
  const lines = [`# ${sess.title}`, ""];
  for (const m of sess.msgs) {
    if (m.role === "user") lines.push(`**用户**：${m.text}`, "");
    else if (m.role === "assistant") lines.push(`**助手**：${m.text}`, "");
    else if (m.role === "meta") lines.push(`> ${m.text}`, "");
    else if (m.role === "tool")
      lines.push(`<details><summary>🛠 ${m.name}</summary>`, "", "```json", m.result || "", "```", "", "</details>", "");
  }
  const doc = await vscode.workspace.openTextDocument({ language: "markdown", content: lines.join("\n") });
  vscode.window.showTextDocument(doc, { preview: true });
}

// ------------------------------------------------------------------ activate --

function activate(context) {
  ctx = context;

  // 归一宿主: 登记 HA 领域塑形器(键 = 机控桥子插件画像 app_id "homeassistant-ext"),
  // domain:homeassistant-ext 模式激活时由单一 Cascade 基底自动塑形(每会话首条注入领域 SP)。
  const unifiedHost = globalThis.__DAO_UNIFIED_HOST__;
  if (unifiedHost && typeof unifiedHost.registerDomainShaper === "function") {
    try {
      let injected = new Set();
      const sp = [
        "你现在处于「Home Assistant 模式」: 你是 DAO HA 归一智能家居代理, 全权代替用户驱动 Home Assistant 底层完成配置/自动化/设备控制。",
        "",
        "## 工具目录 (ha-copilot)",
      ].concat(AGENT_TOOLS.map((t) => "- " + t.name + ": " + t.desc)).concat([
        "",
        "## 操作纪律",
        "- 一切 HA 操作优先经上述工具面(或机控桥 @ha 领域动词: states/call_service/automation_create/check_config)执行, 不要凭记忆编造实体/服务。",
        "- 改配置后必 check_config 校验; 动作后 render_template/states 读回验证再声明完成。",
        "- 回答用简体中文, 结论先行; 道法自然, 无为而无不为。",
      ]).join("\n");
      unifiedHost.registerDomainShaper("homeassistant-ext", {
        wrap(text, wctx) {
          const key = ((wctx && wctx.agent) || "?") + ":" + ((wctx && wctx.epoch) || 0);
          if (injected.has(key)) return "[HA 模式] " + text;
          injected.add(key);
          return "<dao_ha_mode>\n" + sp + "\n</dao_ha_mode>\n\n" + text;
        },
        status() {
          return { mode: "homeassistant-ext", label: "☯ HA",
            hint: "Home Assistant 领域模式: 配置/自动化/设备走 @ha 工具面", spChars: sp.length };
        },
        toggle() { injected = new Set(); },
      });
    } catch (e) { console.error("[dao-ha] 领域塑形器登记失败: " + (e && e.stack ? e.stack : e)); }
  }

  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 90);
  statusBar.command = "haCopilot.connect";
  context.subscriptions.push(statusBar);

  // 右下角生态面板开关：一点即开、再点即关。
  ecoBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 1);
  ecoBar.command = "haCopilot.togglePanel";
  context.subscriptions.push(ecoBar);
  updateEcoBar();

  chatProvider = new ChatViewProvider();
  homeProvider = new HomeTreeProvider();

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("haCopilot.chat", chatProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.window.registerTreeDataProvider("haCopilot.home", homeProvider),
    vscode.workspace.registerFileSystemProvider("hacfg", new HaConfigFs(), {
      isCaseSensitive: true,
    }),
    vscode.commands.registerCommand("haCopilot.connect", cmdConnect),
    vscode.commands.registerCommand("haCopilot.disconnect", cmdDisconnect),
    vscode.commands.registerCommand("haCopilot.openPanel", cmdOpenPanel),
    vscode.commands.registerCommand("haCopilot.togglePanel", cmdTogglePanel),
    vscode.commands.registerCommand("haCopilot.configureLlm", cmdConfigureLlm),
    vscode.commands.registerCommand("haCopilot.agentDoc", cmdAgentDoc),
    vscode.commands.registerCommand("haCopilot.mountConfig", cmdMountConfig),
    vscode.commands.registerCommand("haCopilot.newChat", () => chatProvider.newChat()),
    vscode.commands.registerCommand("haCopilot.refreshHome", () => homeProvider.refresh()),
    vscode.commands.registerCommand("haCopilot.toggleEntity", cmdToggleEntity),
    vscode.commands.registerCommand("haCopilot.mcpConfig", cmdMcpConfig),
    vscode.commands.registerCommand("haCopilot.runTool", cmdRunTool),
    vscode.commands.registerCommand("haCopilot.exportChat", cmdExportChat)
  );

  // Initial connection probe (non-blocking).
  (async () => {
    if (baseUrl() && (await token())) {
      try {
        const cfg = await api("GET", "/api/config");
        setStatus(true, `${cfg.location_name} · HA ${cfg.version}`);
      } catch {
        setStatus(false);
      }
    } else {
      setStatus(false);
    }
  })();

  homeProvider.startLiveSync();
  context.subscriptions.push(new vscode.Disposable(() => homeProvider.stopLiveSync()));
}

function deactivate() {}

module.exports = { activate, deactivate };
