"""Final-query scoring regressions: context is not an official scoring unit."""

from __future__ import annotations

import pytest

from dumemeval.benchmarks.memoryarena.datasets.search import MemoryArenaSearchAdapter
from dumemeval.evaluation import CalculatorBenchmarkScorer, Evaluator
from dumemeval.models import BenchmarkResult, EvalTask, SessionOutcome, TaskExecution
from dumemeval.models.environment import EnvironmentEvidence
from dumemeval.pipeline.metrics_run import pool_benchmark


def search_task(count: int, max_questions: int | None = None) -> EvalTask:
    adapter = MemoryArenaSearchAdapter()
    return adapter.build_tasks(
        adapter.data_type.from_raw(
            [{"id": count, "questions": [f"q{i}" for i in range(count)], "answers": ["yes"] * count}]
        ),
        **({"max_questions": max_questions} if max_questions is not None else {}),
    )[0]


def score_search(
    task: EvalTask, flags: list[bool], calls: list[str], failed: bool = False
) -> BenchmarkResult:
    task.task_environment = {"type": "memoryarena"}

    def judge(pred: str, gold: str, query: str) -> bool:
        calls.append(query)
        return pred == gold

    execution = TaskExecution(
        task_id=task.name,
        task_name=task.name,
        memory_backend="none",
        sessions=[
            SessionOutcome(
                session_id=i + 1,
                success=not (failed and i == len(flags) - 1),
                observation="yes" if flag else "no",
                environment=EnvironmentEvidence(
                    task_id=task.name,
                    env_name="browsecomp-plus",
                    operation="submit",
                    tool="submit",
                    session_id=i + 1,
                    source="agent_submission",
                    info={"retrieval_actions": [f"search-{i}"]},
                ),
            )
            for i, flag in enumerate(flags)
        ],
    )
    result = Evaluator(None, CalculatorBenchmarkScorer("memoryarena_search", judge=judge)).evaluate(
        task, execution
    )
    assert result.benchmark is not None
    return result.benchmark


@pytest.mark.parametrize("flags", [[False, True], [True, False]])
def test_only_original_final_query_is_judged(flags: list[bool]) -> None:
    calls: list[str] = []
    result = score_search(search_task(2), flags, calls)
    assert result.values["accuracy"] == float(flags[-1])
    assert calls == ["q1"]
    assert result.details[0]["score_status"] == "measured"


@pytest.mark.parametrize("case", ["truncated", "failed", "missing"])
def test_unexecuted_final_is_unmeasured_without_judge_call(case: str) -> None:
    calls: list[str] = []
    result = score_search(
        search_task(3, max_questions=2 if case == "truncated" else None),
        [True, True] if case != "failed" else [True] * 3,
        calls,
        failed=case == "failed",
    )
    assert result.values == {}
    assert result.primary_score is None
    assert result.details[0]["official_score"] is None
    assert result.details[0]["score_status"] == "not_measured"
    assert calls == []


def test_query_aggregation_ignores_context_length_and_retains_unmeasured() -> None:
    results = [
        score_search(search_task(2), [False, True], []),
        score_search(search_task(5), [True, True, True, True, False], []),
    ]
    warnings: list[str] = []
    assert pool_benchmark(results, warnings).values["accuracy"] == 0.5
    assert warnings == []
    results.append(score_search(search_task(3, max_questions=2), [True, True], []))
    assert pool_benchmark(results, warnings).values == {}
    assert warnings
