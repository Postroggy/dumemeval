from pathlib import Path
from typing import Any

import pytest

from dumemeval.adapters.base import BaseMemoryAdapter
from dumemeval.core.protocol import MemorySessionTransferProtocol, TestOnlyProtocol
from dumemeval.evaluation import BenchmarkScorer
from dumemeval.execution.executor import SessionExecutor
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import (
    BenchmarkResult,
    EvalTask,
    MemoryOp,
    MemorySpec,
    SessionOutcome,
    SessionSpec,
    Verdict,
)
from dumemeval.pipeline.spec import EvalPipeline


class Memory(BaseMemoryAdapter):
    def __init__(self) -> None:
        super().__init__(MemorySpec(name="none", type="none"))
        self.observed_sessions: list[int] = []

    def setup(self, task: EvalTask) -> None:
        return None

    def seed_history(self, task: EvalTask) -> None:
        return None

    def inject(self, session: SessionSpec, ctx: dict[str, Any]) -> None:
        return None

    def snapshot(self, session: SessionSpec, path: Path) -> Path:
        return path  # tests do not persist snapshots

    def all_ops(self) -> list[MemoryOp]:
        return []

    def observe(self, session: SessionSpec) -> list[MemoryOp]:
        return []

    def observe_execution(self, session: SessionSpec, outcome: SessionOutcome) -> None:
        self.observed_sessions.append(session.id)


class Exec(SessionExecutor):
    async def run_session(self, session: SessionSpec, ctx: dict[str, Any]) -> SessionOutcome:
        return SessionOutcome(session_id=session.id, success=True, observation="ok")


class Score(BenchmarkScorer):
    def score(self, inp: MetricInput) -> BenchmarkResult:
        return BenchmarkResult(benchmark="x", values={"accuracy": 1}, primary_metric="accuracy")


@pytest.mark.asyncio
async def test_pipeline_is_composition_not_benchmark_branch() -> None:
    task = EvalTask(name="x", sessions=[SessionSpec(id=1, instruction="q", memory_inject=False, query="q")])
    result = await EvalPipeline(
        TestOnlyProtocol(), Memory(), Exec(), lambda s: Verdict(label="correct", score=1), Score()
    ).run(task)
    assert result.execution.sessions[0].observation == "ok"
    assert result.benchmark is not None
    assert result.benchmark.primary_score == 1


@pytest.mark.asyncio
async def test_pipeline_composes_multi_session_transfer_without_benchmark_branch() -> None:
    task = EvalTask(
        name="transfer",
        sessions=[
            SessionSpec(id=1, instruction="write", memory_inject=True, query="write"),
            SessionSpec(id=2, instruction="read", memory_inject=True, query="read"),
        ],
    )
    memory = Memory()
    result = await EvalPipeline(MemorySessionTransferProtocol(), memory, Exec(), None, None, ()).run(task)
    assert len(result.execution.sessions) == 2
    assert result.benchmark is None
    assert memory.observed_sessions == [1, 2]
