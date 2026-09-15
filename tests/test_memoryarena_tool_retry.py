"""Actual mounted CLI process retries through the gateway after response loss."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dumemeval.task_environments import agent_tool
from dumemeval.task_environments.gateway import ToolGateway


def test_pending_identity_preserves_json_types(tmp_path: Path) -> None:
    pending = tmp_path / "pending.json"
    original = agent_tool.pending_request(pending, "action", {"flag": True}, None)
    with pytest.raises(SystemExit, match="different"):
        agent_tool.pending_request(pending, "action", {"flag": 1}, None)
    assert agent_tool.pending_request(pending, "action", {"flag": True}, None) == original


@pytest.mark.parametrize("response_loss", ["disconnect", "invalid_json", "handler_error"])
def test_process_retry_has_one_effect(tmp_path: Path, response_loss: str) -> None:
    effects = []
    deliveries = []

    def mutate(call):
        effects.append(call)
        if response_loss == "handler_error":
            raise OSError("mutation completed, artifact write failed")
        return {"effect": len(effects)}

    gateway = ToolGateway("127.0.0.1", mutate, 10)
    token = gateway.bind()

    class Proxy(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            deliveries.append(json.loads(payload))
            status, body = gateway.dispatch(self.headers.get("Authorization", ""), payload)
            if len(deliveries) == 1:
                if response_loss == "disconnect":
                    self.close_connection = True
                    return
                if response_loss == "invalid_json":
                    body = b"{"
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = {
        **os.environ,
        "DUMEMEVAL_TOOL_URL": f"http://127.0.0.1:{server.server_port}/tool",
        "DUMEMEVAL_TOOL_TOKEN": token,
        "DUMEMEVAL_TOOL_TIMEOUT": "2",
        "DUMEMEVAL_TOOL_STATE_DIR": str(tmp_path),
    }

    def invoke(tool="buy", extra=()):
        return subprocess.run(
            [sys.executable, str(Path(agent_tool.__file__)), *extra, tool, '{"item":"A"}'],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

    try:
        first = invoke()
        assert first.returncode != 0
        assert len(effects) == 1
        assert invoke("different").returncode != 0
        assert len(deliveries) == 1, "A different action cannot bypass the pending one"
        second = invoke()
        assert len(effects) == 1
        assert deliveries[0]["request_id"] == deliveries[1]["request_id"]
        assert token not in "".join(p.read_text() for p in tmp_path.rglob("*.json"))
        if response_loss == "handler_error":
            assert second.returncode != 0
        else:
            assert second.returncode == 0
            assert json.loads(second.stdout)["result"]["effect"] == 1
            assert invoke(extra=("--request-id", deliveries[0]["request_id"])).returncode == 0
            assert len(effects) == 1, "Explicit operation IDs also support retry after a successful response"
            assert invoke().returncode == 0
            assert len(effects) == 2, "A confirmed success permits an intentional subsequent action"
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
        gateway.close()
