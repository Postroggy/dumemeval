"""Actual SDK and official worker delivery must not repeat an uncertain judge call."""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dumemeval.artifacts.redaction import Redactor
from dumemeval.evaluation import CalculatorBenchmarkScorer, Evaluator
from dumemeval.models import SessionOutcome, TaskExecution
from dumemeval.models.environment import ArenaRuntimeConfig, ToolCall
from dumemeval.pipeline.scoring import CheckpointedScorer
from dumemeval.task_environments.runtime import MemoryArenaRuntime
from dumemeval.verifier.retry import call_with_retries
from tests.test_memoryarena_contracts import ADAPTERS, raw_case
from tests.test_memoryarena_search_scoring import search_task


@contextmanager
def lost_response_endpoint():
    deliveries = []

    class Endpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            deliveries.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.close_connection = True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", deliveries
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_framework_judge_lost_response_is_unmeasured_without_sdk_or_resume_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    pytest.importorskip(provider)
    monkeypatch.setenv("FIXTURE_JUDGE_KEY", "fixture-only")
    task = search_task(2)
    execution = TaskExecution(
        task_id=task.name,
        task_name=task.name,
        memory_backend="none",
        sessions=[SessionOutcome(session_id=i, success=True, observation="answer") for i in (1, 2)],
    )
    with lost_response_endpoint() as (url, deliveries):
        for _ in range(2):
            scorer = CheckpointedScorer(
                CalculatorBenchmarkScorer(
                    "memoryarena_search",
                    llm_config={
                        "provider": provider,
                        "base_url": url,
                        "api_key_env": "FIXTURE_JUDGE_KEY",
                        "model": "fixture-judge",
                        "max_retries": 3,
                        "skip_failed": True,
                    },
                ),
                tmp_path / "scoring",
                {},
                Redactor({}),
            )
            result = Evaluator(None, scorer).evaluate(task, execution)
            assert result.benchmark.values == {}
            assert result.benchmark.details[0]["score_status"] == "not_measured"
            assert len(deliveries) == 1


@pytest.mark.parametrize("scene,provider", [("math", "openai"), ("phys", "anthropic")])
def test_official_worker_lost_judge_response_is_not_replayed(
    tmp_path: Path, scene: str, provider: str
) -> None:
    reference = os.environ.get("MEMORYARENA_REFERENCE")
    if not reference:
        pytest.skip("Set MEMORYARENA_REFERENCE to the pinned official checkout")
    pytest.importorskip(provider)
    adapter = ADAPTERS[scene]()
    task = adapter.build_tasks(adapter.data_type.from_raw(raw_case(scene)))[0]
    with lost_response_endpoint() as (url, deliveries):
        config = ArenaRuntimeConfig(
            reference=Path(reference),
            env_name=scene,
            agent_host="127.0.0.1",
            gateway_host="127.0.0.1",
            env_config={"backend": provider, "model_name": "fixture-judge"},
            service_env={
                "OPENAI_API_KEY": "fixture-only",
                "OPENAI_BASE_URL": url + "/v1",
                "ANTHROPIC_API_KEY": "fixture-only",
                "ANTHROPIC_BASE_URL": url,
            },
        )
        runtime = MemoryArenaRuntime(task, config, tmp_path)
        try:
            runtime.open()
            assert "max_retries=0" in runtime.service.fingerprint["sdk_retry_policy"]
            # Reset retains the configured client in the pinned Math/Phys implementation.
            runtime.client.reset(seed=37)
            session = task.sessions[0]
            binding = runtime.begin_session(session)
            payload = (
                ToolCall(request_id="one-submission", tool="submit", arguments={"answer": "2"})
                .model_dump_json()
                .encode()
            )
            first = runtime.gateway.dispatch("Bearer " + binding.env["DUMEMEVAL_TOOL_TOKEN"], payload)
            assert first[0] == 502
            assert len(deliveries) == 1
            assert runtime.gateway.dispatch("Bearer " + binding.env["DUMEMEVAL_TOOL_TOKEN"], payload) == first
            assert len(deliveries) == 1
        finally:
            runtime.close()
        assert runtime.service.process is None


def test_explicit_rate_limit_can_retry_without_repeating_accepted_inference() -> None:
    requests = []

    class Rejected(Exception):
        status_code = 429

    def request():
        requests.append("request")
        if len(requests) == 1:
            raise Rejected("rate limit")
        return "accepted"

    assert call_with_retries(request, max_retries=3, sleep_fn=lambda _: None) == "accepted"
    assert len(requests) == 2


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_error_cannot_be_replayed(status: int) -> None:
    requests = []

    class Uncertain(Exception):
        status_code = status

    def request():
        requests.append("request")
        raise Uncertain("unsupported endpoint after unknown upstream outcome")

    with pytest.raises(Uncertain):
        call_with_retries(request, max_retries=3, sleep_fn=lambda _: None)
    assert len(requests) == 1
