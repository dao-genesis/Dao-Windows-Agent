#!/usr/bin/env node
// dao-ide-tools 自检: 描述符构造 / 请求解析 / handler 面(注入假 vscode) / HTTP 宿主端到端。
"use strict";
const assert = require("assert");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const m = require("../dao-ide-tools");

// —— 描述符 ——
const desc = m.buildDescriptor({ invokeUrl: "http://127.0.0.1:1234/invoke", token: "t" });
assert.strictEqual(desc.app_id, "vscode-ide");
assert.strictEqual(desc.mention, "ide");
assert.strictEqual(desc.invoke_url, "http://127.0.0.1:1234/invoke");
assert.strictEqual(desc.token, "t");
assert.strictEqual(desc.verbs.length, 8);
const names = desc.verbs.map((v) => v.name);
for (const n of ["command", "commands", "diagnostics", "definitions", "references", "symbols", "open", "active"]) {
  assert.ok(names.includes(n), "缺动词 " + n);
}
// 无 token 不落 token 字段
assert.strictEqual(m.buildDescriptor({ invokeUrl: "u" }).token, undefined);

// —— 请求解析 ——
assert.strictEqual(m.parseInvoke("{oops").error, "非法 JSON");
assert.ok(m.parseInvoke(JSON.stringify({ verb: "nope" })).error.includes("未知动词"));
const p = m.parseInvoke(JSON.stringify({ verb: "commands", params: { filter: "dao" } }));
assert.strictEqual(p.verb, "commands");
assert.deepStrictEqual(p.params, { filter: "dao" });

// —— 假 vscode 注入的 handler 面 ——
function fakeRange(l, c) { return { start: { line: l, character: c } }; }
const fakeVscode = {
  commands: {
    executeCommand: async (cmd, ...args) => {
      if (cmd === "vscode.executeDefinitionProvider") {
        return [{ uri: { fsPath: "/a.py" }, range: fakeRange(3, 4) }];
      }
      if (cmd === "vscode.executeReferenceProvider") {
        return [{ uri: { fsPath: "/a.py" }, range: fakeRange(1, 0) },
                { uri: { fsPath: "/b.py" }, range: fakeRange(9, 2) }];
      }
      if (cmd === "vscode.executeWorkspaceSymbolProvider") {
        return [{ name: "main", kind: 11, containerName: "",
                  location: { uri: { fsPath: "/a.py" }, range: fakeRange(0, 0) } }];
      }
      return { echoed: [cmd, args] };
    },
    getCommands: async () => ["daoWin.home", "workbench.action.files.save"],
  },
  languages: {
    getDiagnostics: () => [
      [{ fsPath: "/a.py" }, [{ range: fakeRange(2, 0), severity: 0, message: "boom", source: "pyright" }]],
      [{ fsPath: "/b.py" }, []],
    ],
  },
  Uri: { file: (p2) => ({ fsPath: p2 }) },
  Position: function (l, c) { this.line = l; this.character = c; },
  Selection: function (a, b) { this.anchor = a; this.active = b; },
  Range: function (a, b) { this.start = a; this.end = b; },
  window: { activeTextEditor: null },
  workspace: {},
};

(async () => {
  const h = m.makeHandlers(fakeVscode);
  const cmds = await h.commands({ filter: "dao" });
  assert.deepStrictEqual(cmds.commands, ["daoWin.home"]);
  const diags = await h.diagnostics({});
  assert.strictEqual(diags.count, 1);
  assert.strictEqual(diags.diagnostics[0].message, "boom");
  const defs = await h.definitions({ path: "/a.py", line: 5, character: 1 });
  assert.deepStrictEqual(defs.definitions, [{ path: "/a.py", line: 3, character: 4 }]);
  const refs = await h.references({ path: "/a.py", line: 5, character: 1 });
  assert.strictEqual(refs.references.length, 2);
  const syms = await h.symbols({ query: "main" });
  assert.strictEqual(syms.symbols[0].name, "main");
  const act = await h.active({});
  assert.strictEqual(act.active, null);

  // —— HTTP 宿主端到端(带鉴权) ——
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "daoide-"));
  const srv = await m.startIdeTools({ vscode: fakeVscode, token: "sec", discoveryDir: dir });
  assert.ok(fs.existsSync(srv.descriptorPath), "描述符未落盘");
  const onDisk = JSON.parse(fs.readFileSync(srv.descriptorPath, "utf-8"));
  assert.strictEqual(onDisk.invoke_url, srv.invokeUrl);

  function call(body, auth) {
    return new Promise((resolve, reject) => {
      const data = Buffer.from(JSON.stringify(body));
      const req = http.request({
        hostname: "127.0.0.1", port: srv.port, path: "/invoke", method: "POST",
        headers: Object.assign({ "Content-Type": "application/json", "Content-Length": data.length },
          auth ? { Authorization: auth } : {}),
      }, (res) => {
        let raw = "";
        res.on("data", (d) => { raw += d; });
        res.on("end", () => resolve({ status: res.statusCode, body: JSON.parse(raw) }));
      });
      req.on("error", reject);
      req.write(data); req.end();
    });
  }

  let r = await call({ verb: "commands", params: {} });
  assert.strictEqual(r.status, 401);
  r = await call({ verb: "commands", params: { filter: "dao" } }, "Bearer sec");
  assert.strictEqual(r.body.ok, true);
  assert.deepStrictEqual(r.body.value.commands, ["daoWin.home"]);
  r = await call({ verb: "nope" }, "Bearer sec");
  assert.strictEqual(r.body.ok, false);
  assert.ok(r.body.error.includes("未知动词"));
  srv.stop();
  console.log("dao-ide-tools 自检通过 ✓");
})().catch((e) => { console.error(e); process.exit(1); });
