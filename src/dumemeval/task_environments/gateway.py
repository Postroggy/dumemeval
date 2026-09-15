"""Session capabilities and duplicate-delivery protection for agent tool calls."""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from pydantic import JsonValue, ValidationError

from ..models.environment import ToolCall

ToolHandler = Callable[[ToolCall], JsonValue]


class ToolGateway:
    """The public surface has no environment-control or grading-reference API."""

    def __init__(self, host: str, handler: ToolHandler, max_actions: int) -> None:
        self.handler = handler
        self.max_actions = max_actions
        self._token: str | None = None
        self._cache: dict[str, tuple[str, int, bytes]] = {}
        self._lock = threading.RLock()
        gateway = self

        class RequestHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.connection.settimeout(10)
                length = int(self.headers.get("Content-Length", "0"))
                if self.path != "/tool" or not 0 < length <= 1_048_576:
                    self.send_error(400)
                    return
                payload = self.rfile.read(length)
                status, body = gateway.dispatch(self.headers.get("Authorization", ""), payload)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                # Access logs must not retain capabilities or model-generated payloads.
                return

        self.server = ThreadingHTTPServer((host, 0), RequestHandler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def start(self) -> None:
        self.thread.start()

    def bind(self) -> str:
        with self._lock:
            self._token = secrets.token_urlsafe(32)
            self._cache.clear()
            return self._token

    def revoke(self) -> None:
        with self._lock:
            self._token = None

    def dispatch(self, authorization: str, payload: bytes) -> tuple[int, bytes]:
        with self._lock:
            if self._token is None or not hmac.compare_digest(authorization, f"Bearer {self._token}"):
                return 403, b'{"error":"expired or invalid session capability"}'
            try:
                call = ToolCall.model_validate_json(payload)
            except ValidationError:
                return 400, b'{"error":"invalid tool request"}'
            identity = json.dumps([call.tool, call.arguments], sort_keys=True)
            if call.request_id in self._cache:
                previous, status, body = self._cache[call.request_id]
                return (status, body) if previous == identity else (409, b'{"error":"request ID conflict"}')
            if len(self._cache) >= self.max_actions:
                return 429, b'{"error":"session action limit reached"}'
            try:
                result = self.handler(call)
                status = 200
                body = json.dumps({"result": result}, ensure_ascii=False).encode()
            except Exception as exc:
                # Handlers may fail after mutation, including during artifact/serialization I/O.
                # Cache that uncertainty too: replay must not invoke the handler again.
                status = 502
                body = json.dumps(
                    {"error": type(exc).__name__, "message": "Tool failed; inspect host trace."}
                ).encode()
            self._cache[call.request_id] = (identity, status, body)
            return status, body

    def close(self) -> None:
        self.revoke()
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=5)
        self.server.server_close()
