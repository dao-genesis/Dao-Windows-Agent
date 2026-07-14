// vscode_* IDE 对等面(历史四模块工具组之一)收编: 把 IDE 本体能力(命令/诊断/定义/
// 引用/符号/打开/活动编辑器)包成一路本地子插件——起纯 Node HTTP /invoke 端点 +
// 向 ~/.dao/subplugins 落描述符, 机控桥扫描后自动多出 @ide 工作层(樸散為器, 不改框架)。
// 纯逻辑(描述符/请求解析)与 IDE 副作用(vscode API)分离, 供 node 自检直测。
"use strict";
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

const APP_ID = "vscode-ide";

const VERBS = [
  { name: "command", summary: "执行任意 VSCode 命令(workbench/编辑器命令均可)",
    params: { command: "命令 id", args: "可选参数数组" } },
  { name: "commands", summary: "列出全部可用命令 id(可选 filter 子串过滤)",
    params: { filter: "可选子串过滤" } },
  { name: "diagnostics", summary: "汇总工作区诊断(错误/警告), 可按文件过滤",
    params: { path: "可选文件路径过滤" } },
  { name: "definitions", summary: "查某文件某位置符号的定义位置",
    params: { path: "文件路径", line: "0 基行号", character: "0 基列号" } },
  { name: "references", summary: "查某文件某位置符号的全部引用",
    params: { path: "文件路径", line: "0 基行号", character: "0 基列号" } },
  { name: "symbols", summary: "按名字搜工作区符号",
    params: { query: "符号名或子串" } },
  { name: "open", summary: "在编辑器中打开文件(可选跳到行)",
    params: { path: "文件路径", line: "可选 0 基行号" } },
  { name: "active", summary: "看当前活动编辑器(文件/光标/选区/语言)", params: {} },
];

// —— 纯逻辑 ——
function buildDescriptor({ invokeUrl, token, source }) {
  const desc = {
    app_id: APP_ID,
    display_name: "VSCode IDE (对等面·子插件)",
    mention: "ide",
    layer: "domain",
    level: 1,
    source: source || "vscode:dao-windows-agent",
    invoke_url: invokeUrl,
    prompt_snippet: "IDE 对等面：command 执行任意 VSCode 命令；diagnostics 看诊断；" +
      "definitions/references/symbols 走语言服务语义索引；open/active 管编辑器。" +
      "位置一律 0 基行列。",
    verbs: VERBS.map((v) => ({ name: v.name, summary: v.summary, params: v.params })),
  };
  if (token) desc.token = token;
  return desc;
}

function parseInvoke(body) {
  let payload;
  try { payload = JSON.parse(body || "{}"); } catch (e) { return { error: "非法 JSON" }; }
  const verb = String(payload.verb || "");
  if (!VERBS.some((v) => v.name === verb)) return { error: "未知动词: " + verb };
  return { verb, params: payload.params || {} };
}

// —— IDE 执行面(vscode API 注入以便测试) ——
function locToPlain(loc) {
  const uri = loc.uri || (loc.targetUri ? loc.targetUri : null);
  const range = loc.range || loc.targetRange || null;
  return {
    path: uri ? (uri.fsPath || String(uri)) : "",
    line: range ? range.start.line : 0,
    character: range ? range.start.character : 0,
  };
}

function makeHandlers(vscode) {
  return {
    async command(p) {
      const args = Array.isArray(p.args) ? p.args : [];
      const r = await vscode.commands.executeCommand(String(p.command || ""), ...args);
      return { result: r === undefined ? null : r };
    },
    async commands(p) {
      let all = await vscode.commands.getCommands(true);
      const f = String(p.filter || "");
      if (f) all = all.filter((c) => c.includes(f));
      return { commands: all, count: all.length };
    },
    async diagnostics(p) {
      const want = String(p.path || "");
      const out = [];
      for (const [uri, diags] of vscode.languages.getDiagnostics()) {
        const fp = uri.fsPath || String(uri);
        if (want && !fp.includes(want)) continue;
        for (const d of diags) {
          out.push({
            path: fp, line: d.range.start.line, character: d.range.start.character,
            severity: d.severity, message: d.message, source: d.source || "",
          });
        }
      }
      return { diagnostics: out, count: out.length };
    },
    async definitions(p) {
      const uri = vscode.Uri.file(String(p.path || ""));
      const pos = new vscode.Position(Number(p.line || 0), Number(p.character || 0));
      const locs = (await vscode.commands.executeCommand(
        "vscode.executeDefinitionProvider", uri, pos)) || [];
      return { definitions: locs.map(locToPlain) };
    },
    async references(p) {
      const uri = vscode.Uri.file(String(p.path || ""));
      const pos = new vscode.Position(Number(p.line || 0), Number(p.character || 0));
      const locs = (await vscode.commands.executeCommand(
        "vscode.executeReferenceProvider", uri, pos)) || [];
      return { references: locs.map(locToPlain) };
    },
    async symbols(p) {
      const syms = (await vscode.commands.executeCommand(
        "vscode.executeWorkspaceSymbolProvider", String(p.query || ""))) || [];
      return {
        symbols: syms.map((s) => ({
          name: s.name, kind: s.kind,
          container: s.containerName || "",
          path: s.location && s.location.uri ? (s.location.uri.fsPath || "") : "",
          line: s.location && s.location.range ? s.location.range.start.line : 0,
        })),
      };
    },
    async open(p) {
      const doc = await vscode.workspace.openTextDocument(String(p.path || ""));
      const editor = await vscode.window.showTextDocument(doc);
      if (p.line !== undefined) {
        const pos = new vscode.Position(Number(p.line), 0);
        editor.selection = new vscode.Selection(pos, pos);
        editor.revealRange(new vscode.Range(pos, pos));
      }
      return { path: doc.uri.fsPath, languageId: doc.languageId, lineCount: doc.lineCount };
    },
    async active() {
      const ed = vscode.window.activeTextEditor;
      if (!ed) return { active: null };
      return {
        active: {
          path: ed.document.uri.fsPath, languageId: ed.document.languageId,
          line: ed.selection.active.line, character: ed.selection.active.character,
          selection: ed.document.getText(ed.selection),
        },
      };
    },
  };
}

// —— 子插件宿主(HTTP /invoke + 描述符落盘) ——
function startIdeTools({ vscode, token, discoveryDir, log }) {
  const say = log || (() => {});
  const handlers = makeHandlers(vscode);
  const server = http.createServer((req, res) => {
    const reply = (code, body) => {
      const data = JSON.stringify(body);
      res.writeHead(code, { "Content-Type": "application/json; charset=utf-8" });
      res.end(data);
    };
    if (req.method !== "POST" || req.url !== "/invoke") { reply(404, { ok: false, error: "未知路由" }); return; }
    if (token) {
      const auth = req.headers.authorization || "";
      if (auth !== "Bearer " + token) { reply(401, { ok: false, error: "鉴权失败" }); return; }
    }
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", async () => {
      const parsed = parseInvoke(body);
      if (parsed.error) { reply(200, { ok: false, error: parsed.error }); return; }
      try {
        const value = await handlers[parsed.verb](parsed.params);
        reply(200, { ok: true, value });
      } catch (e) {
        reply(200, { ok: false, error: (e && e.message) || String(e) });
      }
    });
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      const invokeUrl = "http://127.0.0.1:" + port + "/invoke";
      const dir = discoveryDir || path.join(os.homedir(), ".dao", "subplugins");
      const desc = buildDescriptor({ invokeUrl, token });
      let descriptorPath = "";
      try {
        fs.mkdirSync(dir, { recursive: true });
        descriptorPath = path.join(dir, APP_ID + ".json");
        fs.writeFileSync(descriptorPath, JSON.stringify(desc, null, 2) + "\n");
      } catch (e) { say("vscode-ide 描述符落盘失败: " + e.message); }
      say("vscode_* IDE 对等面就绪 @ide · " + invokeUrl + (descriptorPath ? " · " + descriptorPath : ""));
      resolve({ server, port, invokeUrl, descriptorPath, stop: () => server.close() });
    });
  });
}

module.exports = { APP_ID, VERBS, buildDescriptor, parseInvoke, makeHandlers, locToPlain, startIdeTools };
