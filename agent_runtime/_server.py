from __future__ import annotations

import asyncio
import inspect
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


class _ToolHandler(BaseHTTPRequestHandler):
    """HTTP handler that dispatches POST /tools/{name}@{version} to registered callables."""

    def do_POST(self) -> None:  # noqa: N802
        prefix = "/tools/"
        if not self.path.startswith(prefix):
            self._reply(404, {"error": "not found"})
            return

        ref = self.path[len(prefix):]
        tools: dict[str, Callable] = self.server._tools  # type: ignore[attr-defined]
        fn = tools.get(ref)
        if fn is None:
            self._reply(404, {"error": f"tool {ref!r} not registered"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            inputs: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError as exc:
            self._reply(400, {"error": f"invalid JSON: {exc}"})
            return

        try:
            if inspect.iscoroutinefunction(fn):
                result = asyncio.run(fn(**inputs))
            else:
                result = fn(**inputs)
        except Exception as exc:  # noqa: BLE001
            self._reply(500, {"error": str(exc)})
            return

        if not isinstance(result, dict):
            self._reply(500, {"error": "tool must return a dict"})
            return

        self._reply(200, result)

    def _reply(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class ToolServer:
    """Local HTTP server that handles tool callbacks from the agent-runtime binary."""

    def __init__(self, tools: dict[str, Callable]) -> None:
        self._tools = tools
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    def start(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ToolHandler)
        server._tools = self._tools  # type: ignore[attr-defined]
        self.port = server.server_address[1]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
