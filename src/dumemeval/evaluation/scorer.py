"""Benchmark scoring boundary, separate from dataset task construction and metrics."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..metrics.core.base import MetricBundle, MetricInput
from ..metrics.core.registry import declared_metric_names, get_benchmark_calculator
from ..models import BenchmarkResult


class BenchmarkScorer(ABC):
    """Official benchmark scoring; never writes into execution or metric state."""

    @abstractmethod
    def score(self, inp: MetricInput) -> BenchmarkResult:
        raise NotImplementedError


class CalculatorBenchmarkScorer(BenchmarkScorer):
    """Adapter for the existing benchmark algorithms during migration."""

    def __init__(self, benchmark: str, **options: Any):
        self.benchmark = benchmark
        self.options = options

    def score(self, inp: MetricInput) -> BenchmarkResult:
        bundle: MetricBundle = get_benchmark_calculator(self.benchmark, **self.options).calculate(inp)
        return BenchmarkResult(
            benchmark=bundle.name,
            primary_metric=_primary_metric(bundle),
            values=bundle.values,
            by_category=bundle.by_category,
            details=bundle.details,
        )


def _primary_metric(bundle: MetricBundle) -> str | None:
    for name in (
        "overall_average_passrate",
        "overall_success",
        "f1",
        "accuracy",
        "score",
        "solving_rate",
        "success_rate",
    ):
        if name in bundle.values:
            return name
    return next(iter(bundle.values), None)


__all__ = ["BenchmarkScorer", "CalculatorBenchmarkScorer", "declared_metric_names"]
