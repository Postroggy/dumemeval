"""Scoring resume must not repeat completed or uncertain judge operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dumemeval.adapters.none import NoneMemoryAdapter
from dumemeval.artifacts.redaction import Redactor
from dumemeval.core.config import ExperimentConfig
from dumemeval.evaluation.scorer import BenchmarkScorer
from dumemeval.execution.executor import SessionExecutor
from dumemeval.lifecycle.parallel import ParallelTaskRunner
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import BenchmarkResult, MemorySpec, SessionOutcome, SessionSpec, TaskExecution
from dumemeval.pipeline import finalize_run
from dumemeval.pipeline.scoring import CheckpointedScorer, ScoringCheckpointError, scoring_context
from dumemeval.verifier.base import Verdict
from tests.test_memoryarena_search_scoring import search_task


def score_input() -> MetricInput:
    task = search_task(2)
    return MetricInput(
        task=task,
        execution=TaskExecution(task_id=task.name, task_name=task.name, memory_backend="none"),
    )


class CounterScorer(BenchmarkScorer):
    def __init__(self, error: bool = False) -> None:
        self.calls = 0
        self.error = error

    def score(self, inp: MetricInput) -> BenchmarkResult:
        self.calls += 1
        if self.error:
            raise OSError("lost judge result")
        return BenchmarkResult(
            benchmark="memoryarena_search", values={"accuracy": 1}, details=[{"raw": 'private-key-"value'}]
        )


def checkpoint(scorer: BenchmarkScorer, directory: Path, **context: Any) -> CheckpointedScorer:
    return CheckpointedScorer(scorer, directory, context, Redactor({"API_KEY": 'private-key-"value'}))


def test_completed_score_reuses_redacted_result(tmp_path: Path) -> None:
    scorer = CounterScorer()
    first = checkpoint(scorer, tmp_path).score(score_input())
    resumed = checkpoint(scorer, tmp_path).score(score_input())
    assert first == resumed
    assert scorer.calls == 1
    assert resumed.details == [{"raw": "[REDACTED]"}]
    assert "private-key" not in next(tmp_path.glob("*.json")).read_text(encoding="utf-8")


@pytest.mark.parametrize("field", ["judge", "sources", "dataset", "evidence"])
def test_changed_inputs_invalidate_previous_score(tmp_path: Path, field: str) -> None:
    scorer = CounterScorer()
    inp = score_input()
    checkpoint(scorer, tmp_path, judge="v1", sources="v1", dataset="v1").score(inp)
    context = {"judge": "v1", "sources": "v1", "dataset": "v1"}
    if field == "evidence":
        inp.execution.sessions.append(SessionOutcome(session_id=1, observation="changed"))
    else:
        context[field] = "v2"
    checkpoint(scorer, tmp_path, **context).score(inp)
    assert scorer.calls == 2


def test_uncertain_attempt_cannot_repeat_judge(tmp_path: Path) -> None:
    scorer = CounterScorer(error=True)
    with pytest.raises(OSError, match="lost judge"):
        checkpoint(scorer, tmp_path).score(score_input())
    with pytest.raises(ScoringCheckpointError, match="No judge was called"):
        checkpoint(scorer, tmp_path).score(score_input())
    assert scorer.calls == 1


def test_judge_environment_fallback_is_part_of_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JUDGE_MODEL", "first-model")
    first = scoring_context({}, {}, tmp_path)
    monkeypatch.setenv("JUDGE_MODEL", "second-model")
    assert scoring_context({}, {}, tmp_path) != first


@pytest.mark.parametrize("damage", ["json", "checksum"])
def test_corrupted_result_cannot_repeat_judge(tmp_path: Path, damage: str) -> None:
    scorer = CounterScorer()
    checkpoint(scorer, tmp_path).score(score_input())
    path = next(tmp_path.glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["result"]["values"]["accuracy"] = 0.0
    path.write_text("{" if damage == "json" else json.dumps(record), encoding="utf-8")
    with pytest.raises(ScoringCheckpointError):
        checkpoint(scorer, tmp_path).score(score_input())
    assert scorer.calls == 1


@pytest.mark.asyncio
async def test_real_pipeline_resume_reuses_agent_execution_and_final_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"agent": 0, "judge": 0}

    class FixedAgent(SessionExecutor):
        async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
            calls["agent"] += 1
            return SessionOutcome(session_id=session.id, success=True, observation="fixed answer")

    class FixedJudge:
        def verify(self, *args: object, **kwargs: object) -> Verdict:
            calls["judge"] += 1
            return Verdict(label="PASS", score=1.0, raw="correct: yes\nconfidence: 100%")

    monkeypatch.setattr("dumemeval.verifier.make_llm_judge", lambda *a, **k: FixedJudge())
    cfg = ExperimentConfig.model_validate(
        {
            "experiment": {"name": "scoring-resume"},
            "memory": {"name": "none", "type": "none"},
            "task": {"sessions": [{"instruction": "s"}, {"instruction": "f"}]},
            "judging": {"type": "rule"},
            "output": {"dir": str(tmp_path), "tasks_dir": str(tmp_path / "tasks")},
        }
    )
    task = search_task(2)
    runner = ParallelTaskRunner(
        lambda _: NoneMemoryAdapter(MemorySpec(name="none", type="none")),
        FixedAgent(),
        output_dir=tmp_path,
        resume=True,
    )
    summaries = []
    for _ in range(2):
        executions = await runner.run([task])
        summaries.append(finalize_run(cfg, [task], executions, runner.adapters, tmp_path))
        assert calls == {"agent": 2, "judge": 1}
    assert summaries[0].benchmark == summaries[1].benchmark
    assert summaries[-1].benchmark is not None
    assert summaries[-1].benchmark.values["accuracy"] == 1
