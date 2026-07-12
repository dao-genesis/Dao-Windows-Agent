"""REST 内核：http.server 薄壳，把 BridgeService.dispatch 暴露为 HTTP /api/*。

    python3 -m bridge.server --port 9930 [--token <TOKEN>]

除 /api/health 外，若设了 --token（或环境变量 DAO_WIN_TOKEN），需带
`Authorization: Bearer <TOKEN>`。纯标准库，无第三方依赖。
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bridge.service import BridgeService
from bridge.subplugin_host import SubpluginHost, load_spec

_SERVICE = BridgeService()
_TOKEN = ""


class _Handler(BaseHTTPRequestHandler):
    server_version = "DaoWinBridge/0.1"

    def _send(self, status: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self, path: str) -> bool:
        if not _TOKEN or path == "/api/health":
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {_TOKEN}"

    def _handle(self, method: str) -> None:
        path = self.path.split("?", 1)[0]
        if not self._authed(path):
            self._send(401, {"error": "未授权：需 Authorization: Bearer <token>"})
            return
        payload = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            if raw:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    self._send(400, {"error": f"请求体非合法 JSON: {exc}"})
                    return
        status, obj = _SERVICE.dispatch(method, path, payload)
        self._send(status, obj)

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def log_message(self, fmt: str, *args: object) -> None:  # 静默默认访问日志
        pass


def main() -> None:
    global _SERVICE, _TOKEN
    ap = argparse.ArgumentParser(description="Dao-Windows-Agent 机控桥 REST 内核")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9930)
    ap.add_argument("--token", default=os.environ.get("DAO_WIN_TOKEN", ""))
    ap.add_argument("--subplugin-spec", default="",
                    help="随桥托管一个子插件 spec，先写描述符再构建 registry")
    ap.add_argument("--subplugin-discovery-dir", default=None,
                    help="子插件描述符目录（默认 ~/.dao/subplugins）")
    args = ap.parse_args()
    _TOKEN = args.token
    subplugin = None
    if args.subplugin_spec:
        from core.subplugin import default_discovery_dir
        if args.subplugin_discovery_dir:
            os.environ["DAO_SUBPLUGIN_DIR"] = args.subplugin_discovery_dir
        subplugin = SubpluginHost(load_spec(args.subplugin_spec))
        subplugin.start()
        descriptor = subplugin.write_descriptor(
            args.subplugin_discovery_dir or default_discovery_dir())
        print(f"[bridge] 子插件就绪 {subplugin.invoke_url} · {descriptor}", flush=True)
    _SERVICE = BridgeService()
    httpd = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"[bridge] REST 内核就绪 http://{args.host}:{args.port}/api/  "
          f"(token={'on' if _TOKEN else 'off'})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    finally:
        if subplugin is not None:
            subplugin.stop()


if __name__ == "__main__":
    main()
