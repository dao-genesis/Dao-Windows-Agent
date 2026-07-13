"""子插件宿主（樸散為器 · 板块三真实对接实例）。

把任意外部驱动（其他仓库的 CLI/脚本成果，如 ha-copilot 的 hactl、Dao-PCB 的
kicad 驱动脚本）经一份 spec JSON 包成一个**真实的**本地子插件：起一个纯 stdlib
HTTP 端点服务 `/invoke`，并向发现目录写出描述符——主插件（core/subplugin.py）
扫描后自动收编为一路 @ 领域工作层，与内置画像一视同仁。

spec schema（描述符超集）：
    {
      "app_id": "homeassistant-ext",
      "display_name": "Home Assistant (智能家居·子插件)",
      "mention": "ha",
      "prompt_snippet": "领域纪律…",
      "token": "可选鉴权",
      "verbs": [
        {"name": "ha_call", "summary": "调用 hactl 服务",
         "params": {"args": "hactl 参数"},
         "shell": "hactl {args}"}          # shell 模板：{param} 占位
      ]
    }

verb 执行面二选一：
  · "shell": 命令模板，参数经 shlex.quote 注入后在 workdir 下执行；
  · 进程内注册 python handler（host.register_handler(verb, fn)），fn(**params)。

用法（真实拉起一路子插件）：
    python3 -m bridge.subplugin_host --spec bridge/subplugin_specs/homeassistant.json
"""
from __future__ import annotations

import argparse
import json
import locale
import os
import shlex
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional


def _decode(data: "bytes | None") -> str:
    """子进程输出稳健解码：先 UTF-8，失败退本地区域编码（中文 Windows 控制台为 GBK）。"""
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False), errors="replace")


def _quote(value: str) -> str:
    """按当前平台 shell 规则引用参数（POSIX→shlex.quote，Windows cmd→双引号）。"""
    if os.name == "nt":
        return '"' + str(value).replace('"', '\\"') + '"'
    return shlex.quote(str(value))


def _render_shell(template: str, params: dict) -> str:
    """把 {param} 占位安全渲染进命令模板（值经平台引用，防注入）。

    列表/元组值按多 token 逐个引用后空格连接（透传型参数如 args=["--domain","light"]），
    标量值整体作为单 token 引用。
    """
    class _Q(dict):
        def __missing__(self, key: str) -> str:
            return ""

    def _render(v) -> str:
        if isinstance(v, (list, tuple)):
            return " ".join(_quote(str(x)) for x in v)
        return _quote(str(v))

    quoted = _Q({k: _render(v) for k, v in params.items()})
    return template.format_map(quoted)


class SubpluginHost:
    """一份 spec = 一路真实子插件：HTTP /invoke 服务 + 描述符写出。"""

    def __init__(self, spec: dict, port: int = 0, workdir: Optional[str] = None) -> None:
        if not spec.get("app_id"):
            raise ValueError("spec 缺 app_id")
        if not spec.get("verbs"):
            raise ValueError(f"[{spec.get('app_id')}] spec 至少要声明一个 verb")
        self.spec = spec
        self.token = str(spec.get("token") or "")
        self.workdir = workdir or os.getcwd()
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._shell: dict[str, str] = {
            str(v["name"]): str(v["shell"])
            for v in spec["verbs"] if v.get("shell")
        }
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._make_handler())
        self._thread: Optional[threading.Thread] = None

    # —— 生命周期 ——
    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def invoke_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/invoke"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread = None
        self._server.server_close()

    def register_handler(self, verb: str, fn: Callable[..., Any]) -> None:
        self._handlers[verb] = fn

    # —— 描述符（供 core/subplugin.py 发现收编）——
    def descriptor(self) -> dict:
        desc = {k: v for k, v in self.spec.items() if k != "verbs"}
        desc["verbs"] = [
            {k: v for k, v in verb.items() if k != "shell"}
            for verb in self.spec["verbs"]
        ]
        desc["invoke_url"] = self.invoke_url
        desc.setdefault("layer", "domain")
        desc.setdefault("level", 1)
        desc.setdefault("source", "subplugin_host")
        return desc

    def write_descriptor(self, discovery_dir: str) -> str:
        os.makedirs(discovery_dir, exist_ok=True)
        path = os.path.join(discovery_dir, self.spec["app_id"] + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.descriptor(), fh, ensure_ascii=False, indent=2)
        return path

    # —— 执行面 ——
    def _invoke(self, verb: str, params: dict, workdir: str) -> dict:
        fn = self._handlers.get(verb)
        if fn is not None:
            try:
                return {"ok": True, "value": fn(**params)}
            except Exception as e:  # noqa: BLE001 - 如实回报
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        template = self._shell.get(verb)
        if template is None:
            return {"ok": False, "error": f"未知动词: {verb}"}
        cmd = _render_shell(template, params)
        if workdir:
            os.makedirs(workdir, exist_ok=True)
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=workdir or self.workdir,  # noqa: S602 - 模板来自本地 spec，参数已 quote
                capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"命令超时: {cmd}"}
        out = _decode(proc.stdout).strip()
        err = _decode(proc.stderr).strip()
        if proc.returncode != 0:
            return {"ok": False, "error": err or f"退出码 {proc.returncode}",
                    "logs": [cmd, out] if out else [cmd]}
        return {"ok": True, "value": out, "logs": [cmd] + ([err] if err else [])}

    def _make_handler(self) -> type:
        host = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # 静默
                pass

            def _reply(self, code: int, body: dict) -> None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:  # noqa: N802 - http.server 约定
                if self.path != "/invoke":
                    self._reply(404, {"ok": False, "error": "未知路由"})
                    return
                if host.token:
                    auth = self.headers.get("Authorization") or ""
                    if auth != "Bearer " + host.token:
                        self._reply(401, {"ok": False, "error": "鉴权失败"})
                        return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except (ValueError, json.JSONDecodeError):
                    self._reply(400, {"ok": False, "error": "非法 JSON"})
                    return
                verb = str(payload.get("verb") or "")
                params = payload.get("params") or {}
                workdir = str(payload.get("workdir") or "")
                self._reply(200, host._invoke(verb, params, workdir))

        return Handler


def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    ap = argparse.ArgumentParser(description="DAO 子插件宿主")
    ap.add_argument("--spec", required=True, help="spec JSON 路径")
    ap.add_argument("--port", type=int, default=0, help="监听端口（默认随机）")
    ap.add_argument("--discovery-dir", default=None,
                    help="描述符发现目录（默认 ~/.dao/subplugins）")
    args = ap.parse_args()
    host = SubpluginHost(load_spec(args.spec), port=args.port)
    host.start()
    from core.subplugin import default_discovery_dir
    path = host.write_descriptor(args.discovery_dir or default_discovery_dir())
    print(f"子插件 {host.spec['app_id']} 就绪 · {host.invoke_url} · 描述符 {path}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        host.stop()


if __name__ == "__main__":
    main()
