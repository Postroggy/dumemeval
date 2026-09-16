"""MemoryArena HTTP lifecycle with explicit failure and mutation semantics.

Source: https://github.com/ZexueHe/MemoryArena/blob/6cd9de14b71915e39ac742a20dc33785e14b6aab/env/env_server.py

The upstream client retries all POSTs. This client deliberately does not: a
purchase or environment step may already have happened when a response is lost.
"""

from __future__ import annotations

import time
from types import TracebackType
from typing import Literal, Self
from uuid import uuid4

import requests
from pydantic import JsonValue, TypeAdapter

from dumemeval.models.environment import EnvironmentEvent, EnvironmentEvidence

from .config import ArenaConnection

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class ArenaClient:
    """Own one isolated environment; readiness and reset are explicit operations."""

    def __init__(self, config: ArenaConnection) -> None:
        self.config = config
        self.task_id = f"dumemeval-{uuid4().hex}"
        self.events: list[EnvironmentEvent] = []
        self._http = requests.Session()
        self._initialized = False
        self._ambiguous = False
        self._closed = False

    def available(self) -> list[str]:
        """Verify that the requested factory is loaded, not merely that a port is open."""
        response = self._request("available", method="GET")
        names = response.get("available_environments")
        if not isinstance(names, list) or self.config.env_name not in names:
            raise RuntimeError(f"MemoryArena environment factory unavailable: {self.config.env_name}")
        return [name for name in names if isinstance(name, str)]

    def tools(self) -> list[JsonValue]:
        self._require_active()
        result = self._request("tools").get("tools")
        if not isinstance(result, list):
            raise ValueError("Official tool catalogue is invalid")
        return result

    def tool(self, name: str, arguments: dict[str, JsonValue]) -> JsonValue:
        self._require_active()
        return self._request("tool", {"tool": name, "arguments": arguments}).get("result")

    def shopping_task(
        self, row: dict[str, JsonValue], output_path: str, *, step_index: int | None = None
    ) -> None:
        """Use the upstream task reconstruction before initializing WebShop."""
        payload: dict[str, JsonValue] = {"row": row, "output_path": output_path}
        if step_index is not None:
            payload["step_index"] = step_index
        self._request("shopping_task", payload)

    def initialize(self) -> None:
        if self._initialized or self._closed or self._ambiguous:
            raise RuntimeError("Environment client cannot be initialized twice or reused")
        self.available()
        # Ownership is recorded before POST, allowing cleanup after a lost response.
        self._initialized = True
        self._request(
            "initialize",
            {"env_name": self.config.env_name, "env_config": self.config.env_config},
        )

    def reset(self, seed: int | None = None) -> EnvironmentEvidence:
        """Reset environment state only; never modify conversation or memory storage."""
        self._require_active()
        return self._evidence("reset", self._request("reset", {"seed": seed}))

    def step(
        self, action: JsonValue, *, ground_truth: JsonValue = None, need_judge: bool = False
    ) -> EnvironmentEvidence:
        self._require_active()
        body: dict[str, JsonValue] = {"action": action, "need_judge": need_judge}
        if ground_truth is not None:
            body["ground_truth"] = ground_truth
        return self._evidence("step", self._request("step", body))

    def observation(self) -> EnvironmentEvidence:
        """Read-only reconciliation remains possible after an ambiguous mutation."""
        self._require_active(allow_ambiguous=True)
        return self._evidence("get_observation", self._request("get_observation"))

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._initialized:
                response = self._request("close")
                if response.get("warning"):
                    self.events[-1].status = "failed"
                    self.events[-1].error_type = "CleanupWarning"
                    raise RuntimeError("MemoryArena reported an environment cleanup warning")
        finally:
            self._closed = True
            self._http.close()

    def _require_active(self, *, allow_ambiguous: bool = False) -> None:
        if not self._initialized or self._closed:
            raise RuntimeError("Environment must be initialized and open")
        if self._ambiguous and not allow_ambiguous:
            raise RuntimeError("Previous mutation is ambiguous; reconcile and start a fresh isolated run")

    def _request(
        self, operation: str, payload: dict[str, JsonValue] | None = None, *, method: str = "POST"
    ) -> dict[str, JsonValue]:
        start = time.monotonic()
        status: Literal["completed", "failed", "ambiguous"] = "completed"
        error_type = None
        mutation = operation in {"initialize", "reset", "step", "close", "tool", "shopping_task"}
        try:
            response = self._http.request(
                method,
                f"{self.config.base_url}/env/{operation}",
                json={"task_id": self.task_id, **(payload or {})} if method == "POST" else None,
                timeout=self.config.timeout_sec,
                allow_redirects=False,
            )
            if response.status_code >= 500 and mutation:
                self._ambiguous = True
            response.raise_for_status()
            if not 200 <= response.status_code < 300:
                raise requests.HTTPError("Unexpected non-success status")
            data = _JSON_OBJECT.validate_json(response.content)
            if data.get("status") != "ok":
                raise ValueError("Environment returned a non-ok or invalid response")
            if method == "POST" and data.get("task_id") != self.task_id:
                raise ValueError("Environment response task_id does not match this client")
            if operation in {"reset", "step", "get_observation"}:
                if "observation" not in data:
                    raise ValueError("Environment response has no observation")
                self._evidence(operation, data)
            return data
        except (requests.RequestException, ValueError) as exc:
            if mutation and not isinstance(exc, requests.HTTPError):
                self._ambiguous = True
            status = "ambiguous" if mutation and self._ambiguous else "failed"
            error_type = type(exc).__name__
            # Do not include the URL, payload, server error body, or secrets in logs.
            raise RuntimeError(f"MemoryArena {operation} {status}: {error_type}") from None
        finally:
            self.events.append(
                EnvironmentEvent(
                    operation=operation,
                    task_id=self.task_id,
                    status=status,
                    elapsed_sec=time.monotonic() - start,
                    error_type=error_type,
                )
            )

    def _evidence(self, operation: str, response: dict[str, JsonValue]) -> EnvironmentEvidence:
        return EnvironmentEvidence.model_validate(
            {
                "task_id": self.task_id,
                "env_name": self.config.env_name,
                "operation": operation,
                **{
                    key: response[key] for key in ("observation", "info", "reward", "done") if key in response
                },
            }
        )

    def __enter__(self) -> Self:
        try:
            self.initialize()
        except BaseException as exc:
            self._cleanup(exc)
            raise
        return self

    def _cleanup(self, error: BaseException | None) -> None:
        try:
            self.close()
        except RuntimeError as cleanup_error:
            if error is None:
                raise
            error.add_note(str(cleanup_error))

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._cleanup(exc)
