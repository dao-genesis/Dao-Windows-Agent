"""DAO prompt library — named, editable system prompts (AI IDE prompt管理).

Prompts are plain JSON on disk under the AI-IDE home so the user can version
or sync them. The ``default`` prompt is generated from the live tool surface
and always available; user prompts override by id.
"""
import json
import os

import dao_llm

_FILE = "prompts.json"

BUILTIN = {
    "default": {
        "name": "DAO 工程师（默认）",
        "body": "",   # empty body = auto-generated from the live tool list
    },
    "reviewer": {
        "name": "模型审查员",
        "body": "You are DAO, a CAD model reviewer inside FreeCAD. Perceive "
                "the document with percept.*/measure tools, report problems "
                "(interference, thin walls, missing fillets) and only modify "
                "geometry when explicitly asked. Reply in the standard JSON "
                "envelope {\"say\", \"calls\", \"done\"}.",
    },
}


def _path():
    return os.path.join(dao_llm.config_home(), _FILE)


def load_all():
    """id -> {name, body}; builtins merged under user overrides."""
    out = {k: dict(v) for k, v in BUILTIN.items()}
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if isinstance(v, dict) and "body" in v:
                    out[k] = {"name": v.get("name", k), "body": v["body"]}
    except (OSError, ValueError):
        pass
    return out


def save(prompt_id, name, body):
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data[prompt_id] = {"name": name, "body": body}
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data[prompt_id]


def delete(prompt_id):
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    if data.pop(prompt_id, None) is None:
        return False
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True


def system_prompt(prompt_id, tools):
    """Resolve a prompt id to the final system prompt string."""
    p = load_all().get(prompt_id) or BUILTIN["default"]
    body = p.get("body") or ""
    if not body:
        return dao_llm.build_system_prompt(tools)
    return body + "\n\nAvailable tools:\n" + dao_llm.tools_block(tools)
