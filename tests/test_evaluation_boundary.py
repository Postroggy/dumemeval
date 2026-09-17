from pytest import MonkeyPatch

from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.metrics.core.base import MetricBundle, MetricInput
from dumemeval.models import BenchmarkResult


def test_benchmark_result_has_explicit_primary_metric() -> None:
    result = BenchmarkResult(benchmark="toy", values={"accuracy": 0.5}, primary_metric="accuracy")
    assert result.primary_score == 0.5


def test_calculator_scorer_returns_benchmark_result(monkeypatch: MonkeyPatch) -> None:
    class FakeCalculator:
        def calculate(self, _: MetricInput) -> MetricBundle:
            return MetricBundle(name="toy", kind="benchmark", values={"score": 0.75})

    monkeypatch.setattr(
        "dumemeval.evaluation.scorer.get_benchmark_calculator", lambda *_a, **_k: FakeCalculator()
    )
    output = CalculatorBenchmarkScorer("toy").score(MetricInput())
    assert isinstance(output, BenchmarkResult)
    assert output.primary_metric == "score"
    assert output.primary_score == 0.75
