"""Runtime boundaries: ownership, isolation, delivery and actual official HTTP."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal

import pytest

from dumemeval.environments import TaskEnvironmentProvider, register_task_environment
from dumemeval.execution.environment import EnvironmentExecutor
from dumemeval.execution.executor import SessionExecutor
from dumemeval.models import EvalTask, SessionOutcome, SessionSpec, TaskEnvSpec
from dumemeval.models.environment import ArenaConnection, ArenaRuntimeConfig, ToolCall
from dumemeval.task_environments.base import EnvironmentBinding, TaskEnvironmentRuntime
from dumemeval.task_environments.gateway import ToolGateway
from dumemeval.task_environments.memoryarena import ArenaClient
from dumemeval.task_environments.service import OfficialService


def test_gateway_duplicate_actions_and_expired_sessions() -> None:
    actions: list[ToolCall] = []

    def buy(call: ToolCall) -> str:
        actions.append(call)
        return "bought"

    gateway = ToolGateway("127.0.0.1", buy, 3)
    try:
        token = gateway.bind()
        payload = ToolCall(request_id="purchase1", tool="buy").model_dump_json().encode()
        first = gateway.dispatch(f"Bearer {token}", payload)
        assert gateway.dispatch(f"Bearer {token}", payload) == first
        assert len(actions) == 1
        conflict = ToolCall(request_id="purchase1", tool="different").model_dump_json().encode()
        assert gateway.dispatch(f"Bearer {token}", conflict)[0] == 409
        gateway.bind()
        assert gateway.dispatch(f"Bearer {token}", payload)[0] == 403
        assert len(actions) == 1
    finally:
        gateway.close()


def test_gateway_does_not_replay_failed_mutation() -> None:
    attempts = 0

    def failure(call: ToolCall) -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("SECRET cannot reach the agent")

    gateway = ToolGateway("127.0.0.1", failure, 1)
    try:
        token = gateway.bind()
        payload = ToolCall(request_id="a", tool="buy").model_dump_json().encode()
        result = gateway.dispatch(f"Bearer {token}", payload)
        assert result[0] == 502 and b"SECRET" not in result[1]
        assert gateway.dispatch(f"Bearer {token}", payload) == result
        assert attempts == 1
    finally:
        gateway.close()


@pytest.mark.asyncio
async def test_environment_scope_closes_after_executor_failure(tmp_path: Path) -> None:
    events: list[str] = []

    class Runtime(TaskEnvironmentRuntime):
        def open(self) -> None:
            events.append("open")

        def begin_session(self, session: SessionSpec) -> EnvironmentBinding:
            events.append("bind")
            return EnvironmentBinding(env={"TOOL": "available"})

        def finish_session(self, session: SessionSpec, outcome: SessionOutcome) -> SessionOutcome:
            events.append("revoke")
            return outcome

        def close(self) -> None:
            events.append("close")

    class Provider(TaskEnvironmentProvider):
        name = "fixture_runtime"

        def endpoint(self, spec: TaskEnvSpec) -> None:
            return None

        def usage_hint(self, spec: TaskEnvSpec) -> None:
            return None

        def env_vars(self, spec: TaskEnvSpec) -> dict[str, str]:
            return {}

        def create_runtime(self, task: EvalTask, spec: TaskEnvSpec, output_dir: Path) -> Runtime:
            return Runtime()

    class FailingExecutor(SessionExecutor):
        async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
            assert session_ctx["agent_env"]["TOOL"] == "available"
            raise RuntimeError("agent failed")

    register_task_environment(Provider)
    task = EvalTask(name="one", task_environment={"type": Provider.name})
    executor = EnvironmentExecutor(FailingExecutor())
    async with executor.task_scope(task, tmp_path) as scoped:
        outcome = await scoped.run_session(SessionSpec(id=1, instruction="run"), {})
        assert not outcome.success and outcome.error == "RuntimeError: agent failed"
    assert events == ["open", "bind", "revoke", "close"]


@pytest.mark.integration
def test_pinned_official_service_real_http_lifecycle(tmp_path: Path) -> None:
    reference = os.environ.get("MEMORYARENA_REFERENCE")
    if not reference:
        pytest.skip("Set MEMORYARENA_REFERENCE to the pinned official checkout")
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    config = ArenaRuntimeConfig(
        reference=Path(reference), env_name="math", service_env={"ANTHROPIC_API_KEY": "fixture-not-used"}
    )
    service = OfficialService(config, tmp_path)
    try:
        service.start()
        client = ArenaClient(
            ArenaConnection(
                base_url=service.url,
                env_name="math",
                env_config={"backend": "anthropic", "model_name": "fixture-not-used"},
            )
        )
        # This test invokes actual official environment code, without a model call.
        import time

        deadline = time.monotonic() + 15
        while True:
            try:
                client.available()
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        with client:
            reset = client.reset(seed=17)
            assert reset.observation["step"] == 0
            first = client.step({"type": "final", "answer": "2"})
            assert first.observation["final"] == "2"
            assert first.observation["step"] == 1
            assert client.observation().observation["state"] == {"history_len": 0}
            assert client.reset(seed=17).observation["step"] == 0
            assert json.dumps(client.tools())
    finally:
        service.close()
    assert service.process is None
    assert "fixture-not-used" not in (tmp_path / "service.log").read_text(encoding="utf-8")


@pytest.mark.integration
@pytest.mark.parametrize("scene", ["math", "phys"])
def test_agent_tool_cross_session_official_http_with_fixture_judge(
    scene: Literal["math", "phys"], tmp_path: Path
) -> None:
    """Real HTTP + pinned environment + a deterministic judge server, not a Harbor run."""
    from dumemeval.task_environments.runtime import MemoryArenaRuntime
    from tests.test_memoryarena_contracts import ADAPTERS, raw_case

    reference = os.environ.get("MEMORYARENA_REFERENCE")
    if not reference:
        pytest.skip("Set MEMORYARENA_REFERENCE to the pinned official checkout")
    pytest.importorskip("anthropic")
    pytest.importorskip("fastapi")
    requests: list[dict[str, Any]] = []

    class FixtureJudge(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps(
                {
                    "id": "fixture",
                    "type": "message",
                    "role": "assistant",
                    "model": "fixture-judge",
                    "content": [{"type": "text", "text": "yes"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    judge = ThreadingHTTPServer(("127.0.0.1", 0), FixtureJudge)
    thread = threading.Thread(target=judge.serve_forever, daemon=True)
    thread.start()
    adapter = ADAPTERS[scene]()
    task = adapter.build_tasks(adapter.data_type.from_raw(raw_case(scene)))[0]
    config = ArenaRuntimeConfig(
        reference=Path(reference),
        env_name=scene,
        agent_host="127.0.0.1",
        gateway_host="127.0.0.1",
        env_config={"backend": "anthropic", "model_name": "fixture-judge"},
        service_env={
            "ANTHROPIC_API_KEY": "fixture-key-for-http-test",
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{judge.server_port}",
        },
    )
    runtime = MemoryArenaRuntime(task, config, tmp_path)
    credentials = []
    try:
        runtime.open()
        for index, session in enumerate(task.sessions):
            binding = runtime.begin_session(session)
            credentials.append(binding.env["DUMEMEVAL_TOOL_TOKEN"])
            assert binding.mounts[0].read_only
            command = [sys.executable, binding.mounts[0].host_path]
            environment = {**os.environ, **binding.env}
            if index == 0:
                catalog = subprocess.run(
                    [*command, "tools"],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                )
                assert "reasoning" in catalog.stdout
                assert str(task.data["answers"][0]) not in catalog.stdout
                reasoning = subprocess.run(
                    [*command, "reasoning", json.dumps({"task": "Compute 1 + 1"})],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                )
                assert "yes" in reasoning.stdout
            subprocess.run(
                [
                    *command,
                    "submit",
                    json.dumps({"answer": "fixture prediction", "ground_truth": "agent-forged"}),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            outcome = runtime.finish_session(session, SessionOutcome(session_id=session.id, success=True))
            assert outcome.success and outcome.environment
            assert outcome.environment.reward == 1 and outcome.environment.observation["step"] == index + 1
            assert outcome.observation == "fixture prediction"
            # Revoked capabilities cannot read or mutate the next session's environment.
            expired = subprocess.run(
                [*command, "tools"], env=environment, capture_output=True, text=True, timeout=30
            )
            assert expired.returncode != 0
        assert len(set(credentials)) == len(task.sessions)
        assert len(requests) == len(task.sessions) + 1
        for request, reference_answer in zip(requests[1:], task.data["answers"], strict=True):
            prompt = json.dumps(request["messages"])
            assert str(reference_answer) in prompt and "agent-forged" not in prompt
    finally:
        runtime.close()
        judge.shutdown()
        judge.server_close()
        thread.join(timeout=5)
    assert runtime.service.process is None
    trace = (runtime.directory / "trace.json").read_text(encoding="utf-8")
    assert all(credential not in trace for credential in credentials)
    assert json.loads(trace)["closed"] is True
