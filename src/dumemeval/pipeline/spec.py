"""Composable pipeline wiring; benchmark and execution choices stay orthogonal."""

from __future__ import annotations

from dataclasses import dataclass

from ..adapters.base import BaseMemoryAdapter
from ..core.protocol import EvalProtocol
from ..evaluation import BenchmarkScorer, Evaluator, Verifier
from ..execution.executor import SessionExecutor
from ..lifecycle.runner import SessionRunner
from ..metrics.core.base import MetricCalculator
from ..models import EvalTask, TaskResult


@dataclass(frozen=True)
class EvalPipeline:
    protocol: EvalProtocol
    memory: BaseMemoryAdapter
    executor: SessionExecutor
    verifier: Verifier | None
    scorer: BenchmarkScorer | None
    metrics: tuple[MetricCalculator, ...] = ()

    async def run(self, task: EvalTask) -> TaskResult:
        execution = await SessionRunner(self.memory, self.executor, self.protocol).run(task)
        return Evaluator(self.verifier, self.scorer, self.metrics).evaluate(task, execution)
