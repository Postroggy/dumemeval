"""Regression coverage for PR #5's scene dispatch and evidence review."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dumemeval.artifacts.redaction import Redactor
from dumemeval.benchmarks.memoryarena.environment import prepare
from dumemeval.benchmarks.memoryarena.environment.client import ArenaClient
from dumemeval.benchmarks.memoryarena.environment.config import ArenaConnection, ArenaRuntimeConfig
from dumemeval.benchmarks.memoryarena.environment.journal import EnvironmentJournal
from dumemeval.benchmarks.memoryarena.environment.official_tools import OfficialTools
from dumemeval.benchmarks.memoryarena.environment.runtime import MemoryArenaRuntime
from dumemeval.benchmarks.memoryarena.environment.scenarios import ToolResult, scenario_type
from dumemeval.benchmarks.memoryarena.environment.service import OfficialService
from dumemeval.benchmarks.memoryarena.metrics.reasoning import MemoryArenaMathCalculator
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import EvalTask, SessionOutcome, SessionSpec, TaskExecution
from dumemeval.models.environment import EnvironmentEvent, EnvironmentEvidence, ToolCall
from dumemeval.models.memoryarena import ARENA_SCENES, arena_scene


@pytest.fixture
def runtime(tmp_path: Path) -> MemoryArenaRuntime:
    session = SessionSpec(id=1, instruction="question", query="question")
    task = EvalTask(name="review", sessions=[session], data={"questions": ["question"], "answers": ["2"]})
    runtime = MemoryArenaRuntime(task, ArenaRuntimeConfig(reference=tmp_path, env_name="math"), tmp_path)
    runtime.client = ArenaClient(ArenaConnection(base_url="http://fixture.invalid", env_name="math"))
    runtime._clients.append(runtime.client)
    runtime.session = session
    return runtime


@pytest.mark.parametrize(
    "error_type", [OSError, TimeoutError, TypeError, RuntimeError, ValueError, KeyError, KeyboardInterrupt]
)
@pytest.mark.parametrize("operation", ["tool", "submit", "feedback"])
def test_every_exception_is_persisted_as_failed(
    runtime: MemoryArenaRuntime,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
    operation: str,
) -> None:
    error = error_type("private error details")

    def fail(*args: object) -> None:
        raise error

    if operation == "tool":
        monkeypatch.setattr(runtime.scenario, "invoke", fail)
    else:
        assert runtime.client is not None
        reply = EnvironmentEvidence(
            task_id=runtime.client.task_id, env_name="math", operation="step", reward=1
        )
        monkeypatch.setattr(runtime.scenario, "submit", fail if operation == "submit" else lambda *_: reply)
        if operation == "feedback":
            monkeypatch.setattr(runtime.scenario, "feedback", fail)
    call = ToolCall(
        request_id="failed-action",
        tool="reasoning" if operation == "tool" else "submit",
        arguments={"answer": "2"},
    )
    with pytest.raises(error_type) as caught:
        runtime._call(call)
    assert caught.value is error
    record = json.loads((runtime.directory / "trace.jsonl").read_text())["record"]
    assert record["status"] == "failed" and record["action_id"] == call.request_id
    assert runtime._submitted is (operation == "feedback")
    if operation == "feedback":
        with pytest.raises(ValueError, match="already submitted"):
            runtime._call(ToolCall(request_id="different-id", tool="submit", arguments={"answer": "2"}))
    assert runtime.session is not None
    outcome = runtime.finish_session(runtime.session, SessionOutcome(session_id=1, success=True))
    assert not outcome.success and outcome.environment is None
    assert json.loads((runtime.directory / "trace.json").read_text())["evidence"][0]["status"] == "failed"


@pytest.mark.parametrize("fresh", [False, True])
def test_only_current_transport_ambiguity_marks_action_ambiguous(
    runtime: MemoryArenaRuntime, monkeypatch: pytest.MonkeyPatch, fresh: bool
) -> None:
    assert runtime.client is not None
    event = EnvironmentEvent(
        task_id=runtime.client.task_id, operation="tool", status="ambiguous", elapsed_sec=0
    )
    runtime.client.events.append(event)

    def fail(client: ArenaClient, call: ToolCall) -> ToolResult:
        if fresh:
            client.events.append(event.model_copy())
        raise OSError("delivery failed")

    monkeypatch.setattr(runtime.scenario, "invoke", fail)
    with pytest.raises(OSError):
        runtime._call(ToolCall(request_id="new", tool="reasoning"))
    assert runtime.evidence[-1].status == ("ambiguous" if fresh else "failed")


def test_calls_append_redacted_records_and_snapshot_at_boundary(
    runtime: MemoryArenaRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = 'secret-"quoted"'
    runtime.service.redactor.secrets.append(secret)

    def invoke(client: ArenaClient, call: ToolCall) -> ToolResult:
        client.events.append(
            EnvironmentEvent(task_id=client.task_id, operation="tool", status="completed", elapsed_sec=0)
        )
        return ToolResult(
            result=secret,
            evidence=EnvironmentEvidence(task_id=client.task_id, env_name="math", operation="step"),
        )

    monkeypatch.setattr(runtime.scenario, "invoke", invoke)
    runtime._write_artifacts()
    original_snapshot = (runtime.directory / "trace.json").read_bytes()
    journal = runtime.directory / "trace.jsonl"
    for index in range(32):
        previous = journal.read_bytes()
        call = ToolCall(request_id=f"action-{index}", tool="reasoning", arguments={"task": "compute"})
        assert runtime._call(call) == secret
        current = journal.read_bytes()
        assert current.startswith(previous)
        assert len(current.splitlines()) == 2 * (index + 1)
        assert (runtime.directory / "trace.json").read_bytes() == original_snapshot
        evidence = runtime.evidence[-1]
        assert (
            evidence.session_id,
            evidence.action_id,
            evidence.sequence,
            evidence.tool,
            evidence.arguments,
        ) == (1, call.request_id, index, call.tool, call.arguments)
        assert evidence.status == "completed"
    runtime.close()
    records = [json.loads(line) for line in journal.read_text().splitlines()]
    snapshot = json.loads((runtime.directory / "trace.json").read_text())
    assert snapshot["closed"]
    assert [r["record"] for r in records if r["kind"] == "evidence"] == snapshot["evidence"]
    assert [r["record"] for r in records if r["kind"] == "lifecycle"] == snapshot["lifecycle"]
    assert all(item["result"] == "[REDACTED]" for item in snapshot["evidence"])
    before = journal.read_bytes()
    runtime.close()
    assert journal.read_bytes() == before


def test_new_journal_attempt_replaces_old_records(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text("old failed attempt\n")
    journal = EnvironmentJournal(path, Redactor({}))
    evidence = [EnvironmentEvidence(task_id="new", env_name="math", operation="reset")]
    journal.flush(evidence, {})
    journal.flush(evidence, {})
    assert len(path.read_text().splitlines()) == 1
    assert json.loads(path.read_text())["record"]["task_id"] == "new"


def test_journal_close_failure_stays_failed_without_advancing_cursors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def broken_open(*args: object, **kwargs: object) -> Iterator[StringIO]:
        yield StringIO()
        raise OSError("buffered write failed")

    journal = EnvironmentJournal(tmp_path / "trace.jsonl", Redactor({}))
    evidence = [EnvironmentEvidence(task_id="task", env_name="math", operation="tool")]
    histories = {
        "task": [EnvironmentEvent(task_id="task", operation="tool", status="completed", elapsed_sec=0)]
    }
    monkeypatch.setattr(Path, "open", broken_open)
    with pytest.raises(OSError, match="buffered write failed"):
        journal.flush(evidence, histories)
    assert journal._evidence_count == 0 and journal._event_counts == {}
    with pytest.raises(RuntimeError, match="start a new runtime attempt"):
        journal.flush(evidence, histories)


@pytest.mark.parametrize("name", list(ARENA_SCENES))
def test_scene_alias_uses_shared_config_strategy_and_preparation(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "review-alias"
    monkeypatch.setitem(ARENA_SCENES, alias, arena_scene(name))
    original = ArenaRuntimeConfig(reference=tmp_path, env_name=name)
    added = ArenaRuntimeConfig(reference=tmp_path, env_name=alias)
    assert ArenaConnection(base_url="http://fixture.invalid", env_name=alias).env_name == alias
    assert scenario_type(alias) is scenario_type(name)
    assert prepare.required_assets(added) == prepare.required_assets(original)
    monkeypatch.setattr(prepare, "verify_reference", lambda *_: {})
    monkeypatch.setattr(prepare, "_module_available", lambda _: False)
    assert prepare.inspect_environment(added).missing == prepare.inspect_environment(original).missing


def test_reasoning_alias_uses_worker_tools_and_official_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "reasoning-alias"
    monkeypatch.setitem(ARENA_SCENES, alias, arena_scene("math"))
    tools = OfficialTools(tmp_path, {}, {name: scene.family for name, scene in ARENA_SCENES.items()})
    assert tools.prepare(alias) == tools.prepare("math")
    assert (
        tools.call(
            alias, SimpleNamespace(reasoning=lambda task: task + " result"), "reasoning", {"task": "2"}
        )
        == "2 result"
    )
    task = EvalTask(
        name="alias",
        sessions=[SessionSpec(id=1, instruction="q", query="q")],
        data={"questions": ["q"], "answers": ["2"]},
        task_environment={"type": "memoryarena"},
    )
    evidence = EnvironmentEvidence(task_id="alias", env_name=alias, operation="step", reward=1)
    execution = TaskExecution(
        task_id=task.name,
        task_name=task.name,
        memory_backend="none",
        sessions=[SessionOutcome(session_id=1, success=True, observation="2", environment=evidence)],
    )
    calculator = MemoryArenaMathCalculator(judge=lambda *_: False)
    assert calculator.calculate(MetricInput(task=task, execution=execution)).values["is_correct"] == 1
    evidence.status = "failed"
    assert calculator.calculate(MetricInput(task=task, execution=execution)).values == {}


def test_unknown_scenes_are_rejected_by_config_and_worker(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Unsupported MemoryArena scene"):
        ArenaRuntimeConfig(reference=tmp_path, env_name="typo")
    with pytest.raises(ValueError, match="Unsupported official tool family"):
        OfficialTools(tmp_path, {}, {}).prepare("typo")


@pytest.mark.integration
def test_scene_alias_initializes_actual_official_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = os.environ.get("MEMORYARENA_REFERENCE")
    if not reference:
        pytest.skip("Set MEMORYARENA_REFERENCE to the pinned official checkout")
    pytest.importorskip("fastapi")
    pytest.importorskip("anthropic")
    alias = "review-reasoning-alias"
    monkeypatch.setitem(ARENA_SCENES, alias, arena_scene("math"))
    service = OfficialService(
        ArenaRuntimeConfig(
            reference=Path(reference), env_name=alias, service_env={"ANTHROPIC_API_KEY": "fixture-not-used"}
        ),
        tmp_path,
    )
    try:
        service.start()
        client = ArenaClient(
            ArenaConnection(
                base_url=service.url,
                env_name=alias,
                env_config={"backend": "anthropic", "model_name": "fixture-not-used"},
            )
        )
        deadline = time.monotonic() + 15
        while True:
            try:
                assert alias in client.available()
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        with client:
            assert client.reset(seed=17).observation["step"] == 0
            tool = client.tools()[0]
            assert isinstance(tool, dict) and tool["name"] == "reasoning"
    finally:
        service.close()


def test_worker_tools_load_without_framework(tmp_path: Path) -> None:
    import dumemeval.benchmarks.memoryarena.environment.official_tools as module

    script = """
import importlib.abc, sys
class NoFramework(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'dumemeval':
            raise ImportError('Worker imported the framework')
sys.meta_path.insert(0, NoFramework())
sys.path.insert(0, sys.argv[1])
from official_tools import OfficialTools
from pathlib import Path
tools = OfficialTools(Path('.'), {}, {'alias': 'reasoning'})
assert tools.prepare('alias')[0]['name'] == 'reasoning'
"""
    subprocess.run(
        [sys.executable, "-c", script, str(Path(module.__file__).parent)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
