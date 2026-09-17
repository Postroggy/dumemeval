"""Application-level evaluation orchestration.

Execution is deliberately an input: this module never runs sessions or mutates it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..metrics.core.base import MetricCalculator, MetricInput, MetricsAggregator
from ..models import (
    EvalTask,
    MemoryFact,
    SampleResult,
    TaskExecution,
    TaskResult,
    Verdict,
)
from .scorer import BenchmarkScorer

Verifier = Callable[[SampleResult], Verdict]


class Evaluator:
    def __init__(
        self,
        verifier: Verifier | None,
        scorer: BenchmarkScorer | None,
        metrics: Sequence[MetricCalculator] = (),
    ) -> None:
        self.verifier, self.scorer, self.metrics = verifier, scorer, list(metrics)

    def evaluate(
        self,
        task: EvalTask,
        execution: TaskExecution,
        *,
        memory_files: dict[str, str] | None = None,
        ground_truth_facts: list[MemoryFact] | None = None,
    ) -> TaskResult:
        samples = []
        for outcome in execution.sessions:
            if not outcome.observation:
                continue
            query = next((s.query or s.instruction for s in task.sessions if s.id == outcome.session_id), "")
            samples.append(
                SampleResult(
                    sample_id=str(outcome.session_id),
                    query=query,
                    response=outcome.observation,
                    ground_truth=_ground_truth(task, query),
                    session_id=outcome.session_id,
                )
            )
        if self.verifier:
            samples = [sample.model_copy(update={"verdict": self.verifier(sample)}) for sample in samples]
        benchmark = (
            self.scorer.score(
                MetricInput(
                    task=task,
                    execution=execution,
                    samples=samples,
                )
            )
            if self.scorer
            else None
        )
        report = None
        if self.metrics:
            extra: dict[str, Any] = {}
            if benchmark is not None and benchmark.primary_score is not None:
                extra["official_task_score"] = benchmark.primary_score
            report = MetricsAggregator(self.metrics).run(
                MetricInput(
                    task=task,
                    execution=execution,
                    samples=samples,
                    benchmark=benchmark,
                    memory_files=memory_files or {},
                    ground_truth_facts=ground_truth_facts or [],
                    extra=extra,
                )
            )
        return TaskResult(
            task_id=execution.task_id,
            task_name=task.name,
            execution=execution,
            samples=samples,
            benchmark=benchmark,
            metrics=report,
        )


def _ground_truth(task: EvalTask, query: str) -> str | None:
    data = task.data if isinstance(task.data, dict) else {}
    questions, answers = data.get("questions") or [], data.get("answers") or []
    for index, item in enumerate(questions):
        candidate = (
            item
            if isinstance(item, str)
            else item.get("question") or item.get("query")
            if isinstance(item, dict)
            else str(item)
        )
        if str(candidate) == query and index < len(answers):
            return str(answers[index])
    return None
