from dumemeval.evaluation.evaluator import Evaluator
from dumemeval.evaluation.scorer import BenchmarkScorer
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import BenchmarkResult, EvalTask, SessionOutcome, SessionSpec, TaskExecution, Verdict


class Scorer(BenchmarkScorer):
    def score(self, inp: MetricInput) -> BenchmarkResult:
        return BenchmarkResult(benchmark="toy", primary_metric="accuracy", values={"accuracy": 1.0})


def test_evaluator_builds_separate_result_chain() -> None:
    task = EvalTask(name="toy", sessions=[SessionSpec(id=1, instruction="q", query="q")])
    execution = TaskExecution(
        task_id="toy",
        task_name="toy",
        memory_backend="none",
        sessions=[SessionOutcome(session_id=1, success=True, observation="answer")],
    )
    result = Evaluator(lambda sample: Verdict(label="correct", score=1), Scorer()).evaluate(task, execution)
    assert result.execution is execution
    assert result.samples[0].verdict is not None
    assert result.samples[0].verdict.score == 1
    assert result.benchmark is not None
    assert result.benchmark.primary_score == 1
