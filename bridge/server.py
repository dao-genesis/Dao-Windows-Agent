"""REST 内核：http.server 薄壳，把 BridgeService.dispatch 暴露为 HTTP /api/*。

    python3 -m bridge.server --port 9930 [--token <TOKEN>]

除 /api/health 外，若设了 --token（或环境变量 DAO_WIN_TOKEN），需带
`Authorization: Bearer <TOKEN>`。纯标准库，无第三方依赖。

另暴露 MCP over HTTP（streamable HTTP）于 `POST /mcp`：与 stdio 形态（
`python -m bridge.mcp`）同一张工具表、同一套 JSON-RPC 处理，且与 /api/*
共享同一进程内 BridgeService（会话/模式/工程态归一）。Cursor/Copilot/云端
Agent 等任意 MCP 客户端配置 `{"url": "http(s)://…/mcp"}` 即插即用；鉴权与
/api/* 同源（Bearer token）。dao-desktop 的 registerRemote({serverUrl:…/mcp})
与本端点同形。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List

from bridge import mcp as mcp_shell
from bridge.service import BridgeService
from bridge.subplugin_host import SubpluginHost, load_spec

_SERVICE = BridgeService()
_TOKEN = ""

# 随桥捆入的子插件 spec 目录（樸散為器：新增一份 spec 即多一路领域子插件，零改码）。
BUNDLED_SPECS_DIR = os.path.join(os.path.dirname(__file__), "subplugin_specs")


def collect_spec_paths(specs: "List[str] | None", specs_dir: "str | None") -> List[str]:
    """归并 spec 路径来源：逐个 --subplugin-spec + 一个目录内全部 *.json，去重保序。

    目录优先展开为其下每个 *.json；显式单 spec 追加其后。同一路径只留一次
    （规范化绝对路径判重），故 firstlogon 既传目录又传单 spec 也不会重复托管。
    """
    out: List[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            out.append(path)

    if specs_dir and os.path.isdir(specs_dir):
        for name in sorted(os.listdir(specs_dir)):
            if name.endswith(".json"):
                _add(os.path.join(specs_dir, name))
    for path in specs or []:
        if path:
            _add(path)
    return out


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

    def _handle_mcp(self, method: str) -> None:
        """MCP over HTTP（streamable HTTP）：POST 单条/批量 JSON-RPC → JSON 应答。

        纯通知（无 id，如 notifications/initialized）按规范回 202 无体。
        GET/DELETE 回 405（本端不开服务端主动流，请求/应答已覆盖全部工具语义）。"""
        if method != "POST":
            self.send_response(405)
            self.send_header("Allow", "POST")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send(400, {"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": f"parse error: {exc}"}})
            return
        batch = isinstance(body, list)
        reqs = body if batch else [body]
        replies = []
        for one in reqs:
            if not isinstance(one, dict):
                replies.append({"jsonrpc": "2.0", "id": None,
                                "error": {"code": -32600, "message": "invalid request"}})
                continue
            resp = mcp_shell.handle_request(one, service=_SERVICE)
            if resp is not None:
                replies.append(resp)
        if not replies:  # 全为通知
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(200, replies if batch else replies[0])

    def _handle(self, method: str) -> None:
        path = self.path.split("?", 1)[0]
        if not self._authed(path):
            self._send(401, {"error": "未授权：需 Authorization: Bearer <token>"})
            return
        if path == "/mcp" or path == "/mcp/":
            self._handle_mcp(method)
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
    # Windows 控制台默认区域码页（cp1252/GBK）编不出中文横幅，启动即崩——与 bridge.mcp
    # 同法收发统一 UTF-8（errors=replace：横幅是日志不是数据，宁降级勿拒启）。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Dao-Windows-Agent 机控桥 REST 内核")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9930)
    ap.add_argument("--token", default=os.environ.get("DAO_WIN_TOKEN", ""))
    ap.add_argument("--subplugin-spec", action="append", default=[],
                    help="随桥托管一个子插件 spec（可重复），先写描述符再构建 registry")
    ap.add_argument("--subplugin-specs-dir", nargs="?", default=None,
                    const=BUNDLED_SPECS_DIR,
                    help="托管该目录下全部 *.json 子插件 spec；不带值时取随桥捆入的 "
                         f"{BUNDLED_SPECS_DIR}")
    ap.add_argument("--subplugin-discovery-dir", default=None,
                    help="子插件描述符目录（默认 ~/.dao/subplugins）")
    args = ap.parse_args()
    _TOKEN = args.token
    subplugins: List[SubpluginHost] = []
    spec_paths = collect_spec_paths(args.subplugin_spec, args.subplugin_specs_dir)
    if spec_paths:
        from core.subplugin import default_discovery_dir
        if args.subplugin_discovery_dir:
            os.environ["DAO_SUBPLUGIN_DIR"] = args.subplugin_discovery_dir
        ddir = args.subplugin_discovery_dir or default_discovery_dir()
        for path in spec_paths:
            host = SubpluginHost(load_spec(path))
            host.start()
            descriptor = host.write_descriptor(ddir)
            subplugins.append(host)
            print(f"[bridge] 子插件就绪 {host.spec['app_id']} · "
                  f"{host.invoke_url} · {descriptor}", flush=True)
    _SERVICE = BridgeService()
    httpd = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"[bridge] REST 内核就绪 http://{args.host}:{args.port}/api/  "
          f"· MCP http://{args.host}:{args.port}/mcp  "
          f"(token={'on' if _TOKEN else 'off'})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    finally:
        for host in subplugins:
            host.stop()


if __name__ == "__main__":
    main()
