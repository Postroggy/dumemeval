"""Standard-library tool client with a session-local pending-request journal."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def session_lock(directory: Path) -> Iterator[None]:
    """OS locks serialize invocations and release when a process dies."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "lock").open("a+b") as handle:
        if sys.platform == "win32":
            import msvcrt

            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def pending_request(path: Path, tool: str, arguments: dict[str, Any], request_id: str | None) -> bytes:
    """Persist identity before dispatch, reusing only the same pending operation."""
    if path.exists():
        try:
            pending = json.loads(path.read_text(encoding="utf-8"))
            valid = (
                isinstance(pending, dict)
                and isinstance(pending.get("request_id"), str)
                and pending["request_id"]
                and json.dumps(
                    [pending.get("tool"), pending.get("arguments")], sort_keys=True, allow_nan=False
                )
                == json.dumps([tool, arguments], sort_keys=True, allow_nan=False)
                and (request_id is None or request_id == pending["request_id"])
            )
        except (ValueError, OSError):
            valid = False
        if not valid:
            raise SystemExit(
                "A different or unreadable request is pending; retry the original command or end this session."
            )
        return json.dumps(pending, allow_nan=False).encode()
    payload = json.dumps(
        {"request_id": request_id or uuid.uuid4().hex, "tool": tool, "arguments": arguments},
        allow_nan=False,
    ).encode()
    if len(payload) > 1_048_576:
        raise SystemExit("Tool request exceeds the gateway size limit.")
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", help="Stable ID for a logical operation; reuse it on retries.")
    parser.add_argument("tool")
    parser.add_argument("arguments", nargs="?", default="{}")
    args = parser.parse_args()
    try:
        arguments = json.loads(args.arguments)
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a JSON object")
        json.dumps(arguments, allow_nan=False)
    except ValueError:
        raise SystemExit("Arguments must be a finite JSON object.") from None
    url, token = os.environ["DUMEMEVAL_TOOL_URL"], os.environ["DUMEMEVAL_TOOL_TOKEN"]
    scope = hashlib.sha256(json.dumps([url, token]).encode()).hexdigest()
    root = Path(os.environ.get("DUMEMEVAL_TOOL_STATE_DIR", tempfile.gettempdir()))
    directory = root / "dumemeval-arena-tools" / scope
    with session_lock(directory):
        pending = directory / "pending.json"
        payload = pending_request(pending, args.tool, arguments, args.request_id)
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=float(os.environ["DUMEMEVAL_TOOL_TIMEOUT"])
            ) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
                if not isinstance(parsed, dict) or "result" not in parsed:
                    raise ValueError("Missing tool result")
            print(body, flush=True)
        except urllib.error.HTTPError as exc:
            print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
            raise SystemExit(
                "Tool failed; request ID retained. Inspect the host trace; repeating this command cannot repeat the action."
            ) from None
        except (OSError, http.client.HTTPException, ValueError):
            raise SystemExit(
                "Tool delivery uncertain; retry the identical command. Pending request ID retained."
            ) from None
        pending.unlink()


if __name__ == "__main__":
    main()
