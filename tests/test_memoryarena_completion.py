"""Observable regressions for evidence, reproducibility and resource ownership."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from dumemeval.artifacts.controls import experiment_controls, observed_controls
from dumemeval.artifacts.redaction import Redactor
from dumemeval.core.config import ExperimentConfig
from dumemeval.execution.environment import _settle
from dumemeval.execution.trial_config import HarborAgentConfig, HarborConfig, MountConfig, build_trial_config
from dumemeval.lifecycle.checkpoint import load_task_result, save_task_result
from dumemeval.metrics.benchmarks.memoryarena import MemoryArenaTravelCalculator
from dumemeval.metrics.benchmarks.memoryarena_reasoning import MemoryArenaMathCalculator
from dumemeval.metrics.benchmarks.memoryarena_search import MemoryArenaSearchCalculator
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import EvalTask, SampleResult, SessionOutcome, SessionSpec, TaskExecution
from dumemeval.verifier.base import Verdict


@pytest.mark.parametrize(
    "calculator", [MemoryArenaTravelCalculator, MemoryArenaSearchCalculator, MemoryArenaMathCalculator]
)
def test_failed_round_cannot_become_zero_score(calculator: Any) -> None:
    task = EvalTask(
        name="failure",
        sessions=[SessionSpec(id=1, instruction="q", query="q")],
        data={"questions": ["q"], "answers": ["a"]},
    )
    inp = MetricInput(
        task=task,
        execution=TaskExecution(
            task_id=task.name,
            task_name=task.name,
            memory_backend="none",
            sessions=[SessionOutcome(session_id=1, error="service unavailable")],
        ),
    )
    bundle = calculator().calculate(inp)
    assert bundle.values == {}
    assert bundle.details[0]["official_score"] is None


@pytest.mark.parametrize("calculator", [MemoryArenaSearchCalculator, MemoryArenaMathCalculator])
def test_skipped_judge_is_unmeasured(calculator: Any) -> None:
    class MissingJudge:
        def verify(self, *args: object, **kwargs: object) -> Verdict:
            return Verdict(label="SKIPPED", reason="fixture unavailable")

    task = EvalTask(
        name="judge",
        sessions=[SessionSpec(id=1, instruction="q", query="q")],
        data={"questions": ["q"], "answers": ["a"]},
    )
    inp = MetricInput(
        task=task,
        execution=TaskExecution(task_id=task.name, task_name=task.name, memory_backend="none"),
        samples=[SampleResult(sample_id="one", session_id=1, query="q", response="a")],
    )
    metric = calculator()
    metric._llm = MissingJudge()
    assert metric.calculate(inp).values == {}


def test_same_count_different_tasks_changes_control_fingerprint() -> None:
    cfg = ExperimentConfig.model_validate(
        {
            "experiment": {"name": "fixture", "protocol": "test_only"},
            "memory": {"name": "none", "type": "none"},
            "task": {"sessions": [{"instruction": "q", "memory_inject": False}]},
        }
    )
    task = EvalTask(name="one", data={"question": "A"})
    first = experiment_controls(cfg, [task])
    task.data["question"] = "B"
    changed = experiment_controls(cfg, [task])
    assert first["tasks"] != changed["tasks"]
    assert first["code"] == changed["code"]
    cfg.agent.max_tokens = 1024
    assert experiment_controls(cfg, [task])["agent"] != changed["agent"]


def test_observed_asset_change_invalidates_comparison(tmp_path: Path) -> None:
    path = tmp_path / "environments" / "task" / "runtime.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"port": 1, "assets": {"corpus": "abc"}}))
    first = observed_controls(tmp_path)
    path.write_text(json.dumps({"port": 2, "assets": {"corpus": "abc"}}))
    assert observed_controls(tmp_path) == first
    path.write_text(json.dumps({"port": 2, "assets": {"corpus": "changed"}}))
    assert observed_controls(tmp_path)["observed_environment"] != first["observed_environment"]


def test_failed_checkpoint_is_rerun(tmp_path: Path) -> None:
    result = TaskExecution(task_id="one", task_name="one", memory_backend="none", status="failed")
    save_task_result(tmp_path, result)
    assert load_task_result(tmp_path, "one") is None


def test_harbor_schema_preserves_version_readonly_tool_and_fresh_conversation(tmp_path: Path) -> None:
    pytest.importorskip("harbor")
    from harbor.models.trial.config import TrialConfig

    config = build_trial_config(
        HarborConfig(agent=HarborAgentConfig(version="2.1.89")),
        SessionSpec(id=1, instruction="q"),
        tmp_path,
        extra_mounts=[MountConfig(source=str(tmp_path / "tool.py"), target="/opt/tool.py", read_only=True)],
    )
    actual = TrialConfig.model_validate(config)
    assert actual.agent.kwargs["version"] == "2.1.89"
    assert actual.agent.resume_trajectory is False and actual.agent.load_trajectory is None
    assert actual.environment.mounts and actual.environment.mounts[0]["read_only"] is True
    assert actual.verifier.override_timeout_sec == 600


def test_exported_json_redacts_escaped_credentials_without_corrupting_trace(tmp_path: Path) -> None:
    secret = 'a-long-secret-"with-quotes"'
    path = tmp_path / "trajectory.json"
    path.write_text(json.dumps({"output": f"a tool printed {secret}"}), encoding="utf-8")
    Redactor({"API_KEY": secret}).tree(tmp_path)
    assert json.loads(path.read_text())["output"] == "a tool printed [REDACTED]"


@pytest.mark.asyncio
async def test_cancel_waits_for_owned_startup_to_finish() -> None:
    entered, release = threading.Event(), threading.Event()
    events: list[str] = []

    def start() -> None:
        entered.set()
        assert release.wait(5)
        events.append("started")

    async def owner() -> None:
        try:
            await _settle(asyncio.to_thread(start))
        finally:
            events.append("closed")

    job = asyncio.create_task(owner())
    assert await asyncio.to_thread(entered.wait, 5)
    job.cancel()
    await asyncio.sleep(0)
    assert not events
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert events == ["started", "closed"]


@pytest.mark.asyncio
async def test_task_retry_does_not_inject_stale_transfer_files(tmp_path: Path) -> None:
    from dumemeval.adapters.none import NoneMemoryAdapter
    from dumemeval.execution.executor import SessionExecutor
    from dumemeval.lifecycle.parallel import ParallelTaskRunner
    from dumemeval.models import MemorySpec

    old = tmp_path / "memory" / "transfer" / "one"
    old.mkdir(parents=True)
    (old / "stale.txt").write_text("previous attempt")
    attempts: set[str] = set()

    class Capture(SessionExecutor):
        async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
            assert "agent_memory_dir" not in session_ctx
            attempts.add(session_ctx["memory_transfer_dir"])
            return SessionOutcome(session_id=session.id, success=True, observation="ok")

    runner = ParallelTaskRunner(
        adapter_factory=lambda _: NoneMemoryAdapter(MemorySpec(name="none", type="none")),
        executor=Capture(),
        output_dir=tmp_path,
    )
    task = EvalTask(
        name="one", sessions=[SessionSpec(id=1, instruction="q"), SessionSpec(id=2, instruction="r")]
    )
    await runner.run([task])
    await runner.run([task])
    assert len(attempts) == 2
    assert (old / "stale.txt").read_text() == "previous attempt"
