"""DAO reverse-access HTTP API — cloud agents plug into the living system.

The mirror image of the LLM brain: ``dao_llm`` lets *this* system call out to
any model; ``dao_api`` lets any outside agent (Devin, a script, another IDE)
call *in* and own the full tool surface — the same 235+ ops, the same live
document, the same whole-project awareness — over plain authenticated HTTP.
Pair it with ``AGENT_ACCESS.md``: an agent that reads that one document can
drive the entire system natively, devin-remote style.

Endpoints (JSON in/out; ``Authorization: Bearer <token>`` on all but health):

- ``GET  /api/health``        liveness + tool count (no auth)
- ``GET  /api/tools``         every tool name the actor exposes
- ``POST /api/act``           ``{"tool", "args"}`` -> one op result
- ``POST /api/batch``         ``{"calls": [{"tool","args"}...]}`` -> results
- ``GET  /api/status``        cheap live heartbeat (doc/selection/undo),
  pollable every second
- ``GET  /api/project``       whole-project state (the closed-loop eye)
- ``GET  /api/project/brief`` the same truth as readable markdown
- ``POST /api/chat``          ``{"text"}`` -> run the configured LLM agent;
  add ``"stream": true`` for Server-Sent Events: each ``say`` / ``action`` /
  ``verify`` event arrives the moment it happens (an AI-IDE watching the
  turn live), closing with one ``done`` event carrying the full result.

Embeddable anywhere an actor exists: inside the FreeCAD GUI (the panel starts
it on a toggle) or around a headless kernel session in tests/CI. The token is
auto-generated once and persisted in the AI-IDE config.
"""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dao_llm
import dao_prompts

DEFAULT_PORT = 9930


def ensure_token(cfg=None):
    """Return the persistent API token, minting one on first use."""
    cfg = cfg or dao_llm.load_config()
    tok = cfg.get("api_token")
    if not tok:
        tok = "dao-" + secrets.token_hex(16)
        cfg["api_token"] = tok
        dao_llm.save_config(cfg)
    return tok


class DaoAPI:
    """One instance wraps one actor; ``start()`` serves until ``stop()``.

    ``actor(tool, args) -> dict`` must be safe to call from server threads
    (the GUI embedding marshals to the main thread; headless kernels are
    already serialized by the wire protocol). ``tools`` lists the surface.
    """

    def __init__(self, actor, tools, token=None, host="127.0.0.1",
                 port=DEFAULT_PORT):
        self.actor = actor
        self.tools = list(tools)
        self.token = token or ensure_token()
        self.host, self.port = host, int(port)
        self._httpd = None
        self._thread = None
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------- #
    def start(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, obj):
                body = json.dumps(obj, ensure_ascii=False,
                                  default=str).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authed(self):
                got = self.headers.get("Authorization", "")
                return got == "Bearer " + api.token

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                if not n:
                    return {}
                return json.loads(self.rfile.read(n).decode("utf-8"))

            def do_GET(self):
                if self.path == "/api/health":
                    return self._reply(200, {"ok": True, "service": "dao",
                                             "tools": len(api.tools)})
                if not self._authed():
                    return self._reply(401, {"error": "bad token"})
                if self.path == "/api/tools":
                    return self._reply(200, {"tools": sorted(api.tools)})
                if self.path == "/api/status":
                    tool = ("gui.status" if "gui.status" in api.tools
                            else "project.brief")
                    return self._reply(*api.call(tool, {}))
                if self.path == "/api/project":
                    return self._reply(*api.call("project.state", {}))
                if self.path == "/api/project/brief":
                    return self._reply(*api.call("project.brief", {}))
                return self._reply(404, {"error": "unknown path"})

            def do_POST(self):
                if not self._authed():
                    return self._reply(401, {"error": "bad token"})
                try:
                    body = self._body()
                except ValueError:
                    return self._reply(400, {"error": "bad json"})
                if self.path == "/api/act":
                    tool = body.get("tool")
                    if tool not in api.tools:
                        return self._reply(
                            400, {"error": "unknown tool: %r" % (tool,)})
                    return self._reply(
                        *api.call(tool, body.get("args") or {}))
                if self.path == "/api/batch":
                    calls = body.get("calls")
                    if not isinstance(calls, list):
                        return self._reply(400, {"error": "'calls' must be a "
                                                          "list"})
                    out = []
                    for c in calls:
                        code, rec = api.call(c.get("tool", ""),
                                             c.get("args") or {})
                        out.append(rec)
                        if code != 200 and body.get("stop_on_error", True):
                            break
                    return self._reply(200, {"results": out})
                if self.path == "/api/chat":
                    text = body.get("text")
                    if not isinstance(text, str) or not text:
                        return self._reply(400, {"error": "'text' required"})
                    if body.get("stream"):
                        return api.chat_stream(text, body, self)
                    return self._reply(*api.chat(text, body))
                return self._reply(404, {"error": "unknown path"})

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="dao-api")
        self._thread.start()
        return self

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # -- execution ------------------------------------------------------- #
    def call(self, tool, args):
        """Run one op under the serialization lock; (http_code, record)."""
        with self._lock:
            try:
                data = self.actor(tool, args)
            except Exception as exc:
                return 500, {"tool": tool, "ok": False,
                             "error": "%s: %s" % (type(exc).__name__, exc)}
        return 200, {"tool": tool, "ok": True,
                     "data": data if isinstance(data, dict)
                     else {"value": data}}

    def _agent(self, body):
        """(agent, None) from config + per-request overrides, or (None, error)."""
        cfg = dao_llm.load_config()
        for k in ("model", "base_url", "api_key", "max_steps"):
            if body.get(k) is not None:
                cfg[k] = body[k]
        if not dao_llm.configured(cfg):
            return None, {"error": "no model configured; POST base_url/"
                                   "api_key/model or set them in config"}
        return dao_llm.LLMAgent(
            lambda t, a: self.actor(t, a), cfg=cfg,
            system_prompt=dao_prompts.system_prompt(
                cfg.get("system_prompt_id", "default"), self.tools)), None

    @staticmethod
    def _result(out):
        return {"say": out["say"], "actions": out["actions"],
                "verify": out.get("verify"), "messages": out["messages"]}

    def chat(self, text, body):
        agent, err = self._agent(body)
        if agent is None:
            return 400, err
        with self._lock:
            out = agent.ask(text, history=body.get("history") or [])
        return 200, self._result(out)

    def chat_stream(self, text, body, handler):
        """Run one turn, pushing SSE frames as the agent speaks and acts."""
        agent, err = self._agent(body)
        if agent is None:
            handler._reply(400, err)
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()

        def emit(kind, payload):
            frame = "event: %s\ndata: %s\n\n" % (
                kind, json.dumps(payload, ensure_ascii=False, default=str))
            handler.wfile.write(frame.encode("utf-8"))
            handler.wfile.flush()

        with self._lock:
            try:
                out = agent.ask(text, history=body.get("history") or [],
                                on_event=emit)
                emit("done", self._result(out))
            except Exception as exc:
                emit("error", {"error": "%s: %s"
                               % (type(exc).__name__, exc)})
