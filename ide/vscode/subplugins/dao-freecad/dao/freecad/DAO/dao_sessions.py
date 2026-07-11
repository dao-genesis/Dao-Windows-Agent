"""DAO conversation store — persistent multi-conversation history (AI IDE 会话).

One JSON file per conversation under ``<aiide home>/conversations``; each file
holds the OpenAI-style message list plus a title, so conversations survive
FreeCAD restarts and are portable across machines.
"""
import json
import os
import time

import dao_llm


def _dir():
    d = os.path.join(dao_llm.config_home(), "conversations")
    os.makedirs(d, exist_ok=True)
    return d


def _path(conv_id):
    return os.path.join(_dir(), conv_id + ".json")


def create(title=None):
    conv_id = time.strftime("c%Y%m%d-%H%M%S")
    n, base = 1, conv_id
    while os.path.exists(_path(conv_id)):
        conv_id = "%s-%d" % (base, n)
        n += 1
    data = {"id": conv_id, "title": title or conv_id, "messages": []}
    _write(conv_id, data)
    return data


def list_all():
    """[{id, title, messages(count)}] newest first."""
    out = []
    for fn in sorted(os.listdir(_dir()), reverse=True):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(_dir(), fn), "r", encoding="utf-8") as f:
                d = json.load(f)
            out.append({"id": d["id"], "title": d.get("title", d["id"]),
                        "count": len(d.get("messages", []))})
        except (OSError, ValueError, KeyError):
            continue
    return out


def load(conv_id):
    try:
        with open(_path(conv_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_messages(conv_id, messages, title=None):
    data = load(conv_id) or {"id": conv_id, "title": title or conv_id}
    data["messages"] = messages
    if title:
        data["title"] = title
    _write(conv_id, data)
    return data


def delete(conv_id):
    try:
        os.remove(_path(conv_id))
        return True
    except OSError:
        return False


def _write(conv_id, data):
    with open(_path(conv_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
