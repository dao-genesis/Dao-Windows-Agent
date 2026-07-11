"""DAO LLM brain — the conversational core that turns FreeCAD into an AI IDE.

This module is deliberately FreeCAD-free so it can be unit-tested headlessly
and reused by any front end (the in-FreeCAD dock panel, a CLI, an MCP server).

Design (mirrors mature AI IDEs — Devin Desktop / Windsurf / Cursor):

* **Provider routing** — one JSON config selects any OpenAI-compatible
  chat-completions endpoint (OpenAI, DeepSeek, Ollama, a Proxy-Pro style
  router, ...). Base URL + key + model are data, not code.
* **Tool-calling loop** — the model answers with a strict JSON envelope
  ``{"say": str, "calls": [{"tool", "args"}...], "done": bool}``; every call is
  executed against an *actor* (the live-document engine inside FreeCAD, or a
  headless kernel session in tests), and the results are fed back until the
  model declares ``done`` or the step budget is spent.
* **Injectable transport** — network I/O goes through a single ``transport``
  callable so tests can script the model deterministically with no network.
"""
import json
import os
import re
import ssl
import urllib.request

_CA_PATHS = ("/etc/ssl/certs/ca-certificates.crt",   # Debian/Ubuntu
             "/etc/pki/tls/certs/ca-bundle.crt",     # RHEL/Fedora
             "/etc/ssl/cert.pem")                    # macOS/BSD


def _ssl_context():
    """An HTTPS context that works even in bundled Pythons (AppImage/conda)
    whose default CA store is empty: prefer certifi, then the env override,
    then well-known system bundles, then the platform default."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    cafile = os.environ.get("SSL_CERT_FILE")
    if not cafile:
        cafile = next((p for p in _CA_PATHS if os.path.exists(p)), None)
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()

# --------------------------------------------------------------------------- #
# configuration (provider routing)
# --------------------------------------------------------------------------- #

DEFAULT_CONFIG = {
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini",
    "temperature": 0.2,
    "max_steps": 12,
    "system_prompt_id": "default",
}


def config_home():
    """Directory holding all AI-IDE state (config / prompts / conversations)."""
    home = os.environ.get("DAO_AIIDE_HOME") or os.path.join(
        os.path.expanduser("~"), ".dao", "aiide")
    os.makedirs(home, exist_ok=True)
    return home


def _config_path():
    return os.path.join(config_home(), "config.json")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged


def configured(cfg=None):
    """True when the provider is usable (a key, or a local/keyless endpoint)."""
    cfg = cfg or load_config()
    if cfg.get("api_key"):
        return True
    url = cfg.get("base_url", "")
    return "localhost" in url or "127.0.0.1" in url


# --------------------------------------------------------------------------- #
# transport (OpenAI-compatible chat completions)
# --------------------------------------------------------------------------- #

def http_transport(cfg, messages):
    """POST to ``{base_url}/chat/completions``; returns the assistant text."""
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": cfg["model"],
        "temperature": cfg.get("temperature", 0.2),
        "messages": messages,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = "Bearer " + cfg["api_key"]
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    ctx = _ssl_context() if url.startswith("https") else None
    with urllib.request.urlopen(req, timeout=cfg.get("timeout", 120),
                                context=ctx) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- #
# envelope parsing
# --------------------------------------------------------------------------- #

def parse_envelope(text):
    """Extract the ``{"say", "calls", "done"}`` envelope from a model reply.

    Tolerates markdown fences and prose around the JSON; a reply with no JSON
    at all is treated as plain speech with no tool calls (done=True).
    """
    candidates = []
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates.extend(fenced)
    brace = text.find("{")
    if brace != -1:
        candidates.append(text[brace:text.rfind("}") + 1])
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if isinstance(obj, dict) and ("say" in obj or "calls" in obj):
            calls = obj.get("calls") or []
            if not isinstance(calls, list):
                calls = []
            good = [c for c in calls
                    if isinstance(c, dict) and isinstance(c.get("tool"), str)]
            return {"say": str(obj.get("say", "")),
                    "calls": good,
                    "done": bool(obj.get("done", not good))}
    return {"say": text.strip(), "calls": [], "done": True}


# --------------------------------------------------------------------------- #
# system prompt
# --------------------------------------------------------------------------- #

_SYSTEM_TEMPLATE = """You are DAO, an AI CAD engineer living inside FreeCAD. \
You perceive and act on the user's live document through precise tools — never \
through images. 道法自然：act minimally, verify each step.

Reply with EXACTLY one JSON object, no other text:
{"say": "<what you tell the user>",
 "calls": [{"tool": "<tool name>", "args": {...}}, ...],
 "done": <true when the task is finished>}

Rules:
- Use only the tools listed below; args are JSON objects.
- After your calls run, you receive TOOL_RESULTS and continue until done.
- Verify geometry with percept.*/measure tools before declaring done.
- All lengths are millimetres.

Available tools:
%s"""


def _catalog_module():
    """Import ``cad_agent.tool_catalog`` (rich Devin-Desktop-style specs)
    from the repo layout; None when running outside the repo."""
    try:
        from cad_agent import tool_catalog
        return tool_catalog
    except ImportError:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))       # freecad/DAO -> repo
    cand = os.path.join(repo, "cad_agent", "tool_catalog.py")
    if not os.path.exists(cand):
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("dao_tool_catalog", cand)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def tools_block(tools):
    """Rich tool listing (name + description + arg contract) when the
    catalog is available; plain sorted names otherwise."""
    cat = _catalog_module()
    if cat is not None and tools:
        try:
            return cat.prompt_block(list(tools))
        except Exception:
            pass
    return ", ".join(sorted(tools))


def build_system_prompt(tools):
    return _SYSTEM_TEMPLATE % tools_block(tools)


# --------------------------------------------------------------------------- #
# the agent loop
# --------------------------------------------------------------------------- #

class LLMAgent:
    """Conversation-driven tool-calling loop.

    ``actor(tool, args) -> dict`` executes one op (raising on failure is fine;
    errors are captured and fed back to the model so it can self-correct).
    """

    def __init__(self, actor, cfg=None, system_prompt=None, transport=None):
        self.actor = actor
        self.cfg = cfg or load_config()
        self.system_prompt = system_prompt or build_system_prompt([])
        self.transport = transport or http_transport

    def ask(self, user_text, history=None, on_event=None):
        """Run one user turn to completion, then close the perception loop:
        read ``project.state`` back and, if the model's work left diagnosed
        issues, feed them in for corrective rounds. Returns the transcript:
        ``{"say": [...], "actions": [...], "verify": {...}, "messages": [...]}``
        where ``messages`` is the updated history to persist."""
        emit = on_event or (lambda kind, payload: None)
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_text})
        says, actions = [], []
        snapped = self._snapshot_turn()
        self._loop(messages, says, actions, emit)
        verify = self._verify(messages, says, actions, emit, snapped)
        # history to persist excludes the system prompt (rebuilt each turn)
        return {"say": says, "actions": actions, "verify": verify,
                "messages": messages[1:]}

    def _loop(self, messages, says, actions, emit):
        for _step in range(int(self.cfg.get("max_steps", 12))):
            reply = self.transport(self.cfg, messages)
            messages.append({"role": "assistant", "content": reply})
            env = parse_envelope(reply)
            if env["say"]:
                says.append(env["say"])
                emit("say", env["say"])
            if not env["calls"]:
                break
            results = []
            for call in env["calls"]:
                tool, args = call["tool"], call.get("args") or {}
                try:
                    data = self.actor(tool, args)
                    rec = {"tool": tool, "ok": True, "args": args, "data": data}
                except Exception as exc:
                    rec = {"tool": tool, "ok": False, "args": args,
                           "error": "%s: %s" % (type(exc).__name__, exc)}
                results.append(rec)
                actions.append(rec)
                emit("action", rec)
            messages.append({
                "role": "user",
                "content": "TOOL_RESULTS: " + json.dumps(
                    results, ensure_ascii=False, default=str)})
            if env["done"]:
                break

    _READONLY = ("percept.", "measure.", "project.", "doc.", "analyze.")
    _TURN_SNAP = "__turn__"

    def _snapshot_turn(self):
        """Baseline the model before the turn so the post-turn verify can
        report *what changed* (project.diff), not just whether issues remain."""
        try:
            self.actor("project.snapshot",
                       {"label": self._TURN_SNAP, "features": False})
            return True
        except Exception:
            return False

    def _verify(self, messages, says, actions, emit, snapped=False):
        """The closed loop: after acting, *look* — one ``project.state`` call
        holds the whole model like a source file, and ``project.diff`` against
        the pre-turn snapshot shows what this turn really did. Diagnosed
        issues go back to the model for correction (a bounded number of
        rounds)."""
        if not any(a["ok"] and not a["tool"].startswith(self._READONLY)
                   for a in actions):
            return None
        verify = None
        for _round in range(int(self.cfg.get("verify_rounds", 1)) + 1):
            try:
                st = self.actor("project.state", {"features": False})
            except Exception as exc:
                return {"ok": None, "error": str(exc)}
            verify = {"ok": bool(st.get("ok", True)),
                      "issues": st.get("issues") or []}
            if snapped:
                try:
                    d = self.actor("project.diff",
                                   {"base": self._TURN_SNAP,
                                    "features": False})
                    verify["diff"] = {
                        "added": d.get("added") or [],
                        "removed": d.get("removed") or [],
                        "changed": [c.get("object") for c in
                                    (d.get("changed") or [])],
                        "markdown": d.get("markdown", "")}
                except Exception:
                    pass
            emit("verify", verify)
            if verify["ok"] or _round >= int(self.cfg.get("verify_rounds", 1)):
                break
            messages.append({
                "role": "user",
                "content": "POST_TURN_VERIFY: project.state reports these "
                           "issues in the model you just touched: %s\n"
                           "Fix them with tools, then set done=true." %
                           json.dumps(verify["issues"], ensure_ascii=False,
                                      default=str)})
            self._loop(messages, says, actions, emit)
        return verify
