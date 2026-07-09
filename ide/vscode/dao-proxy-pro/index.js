// dao-proxy-pro (vendored slice) · 提示词隔离替换引擎 · 三插件融合之第三翼
// 真源: windsurf-assistant/plugins/dao-proxy-pro/vendor/外接api/core/sp_invert.js
// 融合方式: 引擎读 ~/.dao/mode.json 模式契约(ModeManager 写入) →
//   coding 模式官方原貌不道化; 其余模式官方 SP 整体替换为帛书经文 + 模式 overlay。
// 樸散則為器: 只收编纯文本变换的 SP 引擎薄片, 不拖 MITM/证书/LS 代理重器。
const spInvert = require("./sp_invert.js");

let vscode = null;
try { vscode = require("vscode"); } catch (_) {}

// 模式感知的 SP 变换: 官方形状 → 道化(经文+overlay); coding 模式/非官方 → 原样。
function applySP(text) {
  if (typeof text !== "string" || !text) return text;
  const out = spInvert.invertSP(text);
  return out == null ? text : out;
}

function status() {
  const st = spInvert.getModeState();
  return {
    engine: "sp_invert",
    loaded: spInvert.isLoaded(),
    canon: spInvert.getCanon(),
    canon_chars: spInvert.getCanonChars(),
    mode: st ? st.mode : null,
    overlay_chars: st && st.overlay ? st.overlay.length : 0,
  };
}

function activateDaoProxyPro(context, opts) {
  const ns = (opts && opts.ns) || "daoWin";
  const log = (opts && opts.log) || (() => {});
  if (!vscode) { log("非 IDE 环境, 仅引擎可用"); return { applySP, status, engine: spInvert }; }
  context.subscriptions.push(
    vscode.commands.registerCommand(ns + ".proxy.status", () => {
      const s = status();
      vscode.window.showInformationMessage(
        "DAO 提示词引擎 · 经藏 " + s.canon + " (" + s.canon_chars + " 字) · 模式 " +
        (s.mode || "无契约") + (s.overlay_chars ? " · overlay " + s.overlay_chars + " 字" : "")
      );
    }),
    vscode.commands.registerCommand(ns + ".proxy.preview", async () => {
      const doc = await vscode.workspace.openTextDocument({
        language: "markdown",
        content: applySP("You are Cascade, an AI coding assistant.\n(官方 SP 预览样例)"),
      });
      vscode.window.showTextDocument(doc, { preview: true });
    })
  );
  log("提示词隔离引擎就位 · " + JSON.stringify(status()));
  return { applySP, status, engine: spInvert };
}

module.exports = { activateDaoProxyPro, applySP, status, engine: spInvert };
