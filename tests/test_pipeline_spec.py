import pytest

from dumemeval.core.protocol import TestOnlyProtocol
from dumemeval.evaluation import BenchmarkScorer
from dumemeval.models import BenchmarkResult, EvalTask, SessionOutcome, SessionSpec, Verdict
from dumemeval.pipeline.spec import EvalPipeline


class Memory:
    name = "none"

    def setup(self, task):
        pass

    def seed_history(self, task):
        pass

    def inject(self, session, ctx):
        pass

    def snapshot(self, session, path):
        pass

    def all_ops(self):
        return []

    def observe(self, session):
        return []


class Exec:
    async def run_session(self, session, ctx):
        return SessionOutcome(session_id=session.id, success=True, observation="ok")


class Score(BenchmarkScorer):
    def score(self, inp):
        return BenchmarkResult(benchmark="x", values={"accuracy": 1}, primary_metric="accuracy")


@pytest.mark.asyncio
async def test_pipeline_is_composition_not_benchmark_branch():
    task = EvalTask(name="x", sessions=[SessionSpec(id=1, instruction="q", memory_inject=False, query="q")])
    result = await EvalPipeline(
        TestOnlyProtocol(), Memory(), Exec(), lambda s: Verdict(label="correct", score=1), Score()
    ).run(task)
    assert result.execution.sessions[0].observation == "ok"
    assert result.benchmark.primary_score == 1


@pytest.mark.asyncio
async def test_pipeline_composes_multi_session_transfer_without_benchmark_branch():
    task = EvalTask(
        name="transfer",
        sessions=[
            SessionSpec(id=1, instruction="write", memory_inject=True, query="write"),
            SessionSpec(id=2, instruction="read", memory_inject=True, query="read"),
        ],
    )
    result = await EvalPipeline(
        __import__(
            "dumemeval.core.protocol", fromlist=["MemorySessionTransferProtocol"]
        ).MemorySessionTransferProtocol(),
        Memory(),
        Exec(),
        None,
        None,
        (),
    ).run(task)
    assert len(result.execution.sessions) == 2
    assert result.benchmark is None
