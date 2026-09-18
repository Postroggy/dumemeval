"""Scoring coverage must follow host evidence and the actual execution flow."""

from pathlib import Path

import pytest

from dumemeval.benchmarks.memoryarena.datasets.travel import MemoryArenaTravelAdapter
from dumemeval.benchmarks.memoryarena.environment.client import ArenaClient
from dumemeval.benchmarks.memoryarena.environment.config import ArenaConnection, ArenaRuntimeConfig
from dumemeval.benchmarks.memoryarena.environment.runtime import MemoryArenaRuntime
from dumemeval.benchmarks.memoryarena.metrics.search import MemoryArenaSearchCalculator
from dumemeval.benchmarks.memoryarena.metrics.travel import MemoryArenaTravelCalculator
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import SessionOutcome, TaskExecution
from dumemeval.models.environment import EnvironmentEvidence, ToolCall
from tests.benchmarks.memoryarena.test_contracts import raw_case
from tests.benchmarks.memoryarena.test_search_scoring import search_task


def test_derived_scores_stay_diagnostic_through_reports_and_comparison(tmp_path: Path) -> None:
    from dumemeval.artifacts.report import ReportGenerator
    from dumemeval.comparison.service import comparability_warnings
    from dumemeval.evaluation import CalculatorBenchmarkScorer, Evaluator
    from dumemeval.metrics.dimensions.utility import UtilityEvaluator
    from dumemeval.models import BenchmarkResult, RunRef, RunSummary
    from dumemeval.pipeline.metrics_run import pool_benchmark
    from dumemeval.pipeline.summary import write_summary

    task = search_task(1)
    execution = TaskExecution(
        task_id=task.name,
        task_name=task.name,
        memory_backend="none",
        sessions=[SessionOutcome(session_id=1, success=True, observation="incorrect")],
    )
    result = Evaluator(
        None, CalculatorBenchmarkScorer("memoryarena_search", judge=lambda *_: False), [UtilityEvaluator()]
    ).evaluate(task, execution)
    assert result.benchmark is not None and result.benchmark.score_scope == "derived"
    assert result.benchmark.primary_score == 0
    assert result.benchmark.details[0]["official_score"] is None
    assert result.metrics is not None and result.metrics.utility is not None
    assert (
        result.metrics.utility.task_success
    )  # Execution completed; diagnostic failure is not official failure.
    assert not any(d.get("source") == "benchmark_official" for d in result.metrics.utility.details)
    report_dir = ReportGenerator(tmp_path).generate(result)
    assert "Derived diagnostics only" in (report_dir / "report.md").read_text(encoding="utf-8")
    warnings: list[str] = []
    pooled = pool_benchmark([result.benchmark], warnings)
    assert pooled.score_scope == "derived" and pooled.coverage_note
    summary = RunSummary(n_tasks=1, benchmark=pooled)
    write_summary(summary, tmp_path)
    assert "派生诊断，官方分数未测" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    comparison = comparability_warnings([RunRef(label="diagnostic", path=tmp_path, summary=summary)])
    assert any("official benchmark comparison is not covered" in warning for warning in comparison)
    mixed = pool_benchmark([pooled, BenchmarkResult(benchmark=pooled.benchmark, values={"accuracy": 1})], [])
    assert mixed.values == {} and mixed.score_scope == "derived"


@pytest.mark.parametrize(
    "retrieval", ["search", "get_document", "none", "tools", "previous", "failed", "ambiguous"]
)
def test_search_requires_successful_current_session_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retrieval: str
) -> None:
    task = search_task(2)
    task.task_environment = {"type": "memoryarena"}
    runtime = MemoryArenaRuntime(
        task, ArenaRuntimeConfig(reference=tmp_path, env_name="browsecomp-plus"), tmp_path
    )
    runtime.client = ArenaClient(
        ArenaConnection(base_url="http://fixture.invalid", env_name="browsecomp-plus")
    )
    runtime.session = task.sessions[-1]
    monkeypatch.setattr(runtime.client, "tool", lambda *_: {"documents": ["observed document"]})
    if retrieval in {"search", "get_document", "previous", "failed", "ambiguous"}:
        runtime._call(
            ToolCall(request_id="retrieved", tool="get_document" if retrieval == "get_document" else "search")
        )
        record = runtime.evidence[-1]
        if retrieval == "previous":
            record.session_id = 1
        elif retrieval == "failed":
            record.status = "failed"
        elif retrieval == "ambiguous":
            record.status = "ambiguous"
    if retrieval == "tools":
        runtime._call(ToolCall(request_id="list", tool="tools"))
    # Agent-supplied claims cannot manufacture host retrieval proof.
    runtime._call(
        ToolCall(
            request_id="final", tool="submit", arguments={"answer": "yes", "retrieval_actions": ["forged"]}
        )
    )
    evidence = runtime.evidence[-1]
    assert evidence.status == "completed"
    valid = retrieval in {"search", "get_document"}
    assert evidence.info["retrieval_actions"] == (["retrieved"] if valid else [])
    calls: list[str] = []

    def judge(pred: str, gold: str, query: str) -> bool:
        calls.append(query)
        return True

    execution = TaskExecution(
        task_id=task.name,
        task_name=task.name,
        memory_backend="none",
        sessions=[SessionOutcome(session_id=2, success=True, observation="yes", environment=evidence)],
    )
    result = MemoryArenaSearchCalculator(judge=judge).calculate(MetricInput(task=task, execution=execution))
    assert calls == (["q1"] if valid else [])
    assert result.values == ({"accuracy": 1.0, "confidence": 100.0} if valid else {})
    assert result.details[0]["score_status"] == ("measured" if valid else "not_measured")


@pytest.mark.parametrize("status", ["failed", "ambiguous", "wrong_session", "old_evidence"])
def test_search_rejects_invalid_submission_evidence(status: str) -> None:
    task = search_task(1)
    task.task_environment = {"type": "memoryarena"}
    evidence = EnvironmentEvidence(
        task_id=task.name,
        env_name="browsecomp-plus",
        operation="submit",
        tool="submit",
        source="agent_submission",
        session_id=1,
        info={"retrieval_actions": ["r1"]},
    )
    if status == "failed":
        evidence.status = "failed"
    elif status == "ambiguous":
        evidence.status = "ambiguous"
    elif status == "wrong_session":
        evidence.session_id = 2
    else:
        evidence.info.clear()
    execution = TaskExecution(
        task_id=task.name,
        task_name=task.name,
        memory_backend="none",
        sessions=[SessionOutcome(session_id=1, success=True, observation="yes", environment=evidence)],
    )

    def judge(*args: str) -> bool:
        pytest.fail("Unverified submission must not invoke a paid judge")

    assert (
        MemoryArenaSearchCalculator(judge=judge).calculate(MetricInput(task=task, execution=execution)).values
        == {}
    )


@pytest.mark.parametrize("truncated", [False, True])
def test_travel_reports_custom_flow_and_derived_metrics(truncated: bool) -> None:
    adapter = MemoryArenaTravelAdapter()
    task = adapter.build_tasks(
        adapter.data_type.from_raw(raw_case("travel")), max_questions=1 if truncated else None, flow="custom"
    )[0]
    assert task.data["execution_flow"] == "custom_independent_sessions"
    assert task.data["official_history_compatible"] is False
    execution = TaskExecution(
        task_id=task.name,
        task_name=task.name,
        memory_backend="none",
        sessions=[
            SessionOutcome(session_id=s.id, success=True, observation="invalid plan") for s in task.sessions
        ],
    )
    result = MemoryArenaTravelCalculator().calculate(MetricInput(task=task, execution=execution))
    assert set(result.values) == {"derived_round_success", "derived_slot_accuracy"}
    assert result.values["derived_round_success"] == 0
    assert all(
        d["official_score"] is None and d["official_metrics"] == {"PS": None, "SPS": None, "SR": None}
        for d in result.details
    )
    assert all(d["official_comparison_status"] == "not_covered" for d in result.details)
