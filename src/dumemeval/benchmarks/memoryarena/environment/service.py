"""Bounded ownership of the pinned upstream server process."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from pydantic import JsonValue

from dumemeval.artifacts.redaction import Redactor

from .config import ArenaRuntimeConfig


def verify_reference(reference: Path, revision: str) -> dict[str, str]:
    """Refuse a different or modified official implementation before execution."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(reference), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        ).stdout.strip()

    if git("rev-parse", "HEAD") != revision:
        raise ValueError(f"MemoryArena checkout must be at {revision}")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("MemoryArena tracked source is modified")
    digest = hashlib.sha256()
    for name in git("ls-files", "env").splitlines():
        path = reference / name
        if path.is_file():
            digest.update(name.encode())
            digest.update(path.read_bytes())
    return {"revision": revision, "environment_source_sha256": digest.hexdigest()}


class OfficialService:
    """Start one isolated server, discover its chosen port and always reap it."""

    def __init__(self, config: ArenaRuntimeConfig, output_dir: Path, mode: str = "environment") -> None:
        self.config = config
        self.output_dir = output_dir
        self.process: subprocess.Popen[str] | None = None
        self.url = ""
        self.fingerprint: dict[str, JsonValue] = {}
        self.redactor = Redactor({**os.environ, **config.service_env})
        self._threads: list[threading.Thread] = []
        self.mode = mode

    def start(self) -> None:
        self.fingerprint.update(verify_reference(self.config.reference, self.config.revision))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        script = Path(__file__).with_name("official.py")
        command = [
            self.config.python or sys.executable,
            str(script),
            str(self.config.reference.resolve()),
            self.mode,
        ]
        environment = {**os.environ, **self.config.service_env, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert self.process.stdin and self.process.stdout and self.process.stderr
        self.process.stdin.write(json.dumps(self.config.tools_config) + "\n")
        self.process.stdin.flush()
        self.process.stdin.close()
        ready: queue.Queue[str] = queue.Queue()

        def read_ready() -> None:
            assert self.process and self.process.stdout
            ready.put(self.process.stdout.readline())

        def log_errors() -> None:
            assert self.process and self.process.stderr
            with (self.output_dir / "service.log").open("w", encoding="utf-8") as log:
                for line in self.process.stderr:
                    log.write(self.redactor.text(line))
                    log.flush()

        self._threads = [threading.Thread(target=fn, daemon=True) for fn in (read_ready, log_errors)]
        for thread in self._threads:
            thread.start()
        try:
            message = json.loads(ready.get(timeout=self.config.startup_timeout_sec))
            port = int(message["port"])
            if not 0 < port < 65536:
                raise ValueError("Invalid official service port")
            self.url = f"http://127.0.0.1:{port}"
            self.fingerprint.update(message)
        except (queue.Empty, ValueError, KeyError) as exc:
            self.close()
            raise RuntimeError(
                f"Official server startup failed ({type(exc).__name__}); see service.log"
            ) from None

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.fingerprint["process_exit_code"] = process.returncode
        for thread in self._threads:
            thread.join(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()
        self.process = None
