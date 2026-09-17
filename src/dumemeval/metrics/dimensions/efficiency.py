"""Efficiency 指标：write/retrieval latency、tokens、cost。"""

from __future__ import annotations

from itertools import pairwise
from typing import ClassVar

from ...models import MEMORY_READ_OPS, MEMORY_WRITE_OPS, EfficiencyResult, MemoryOp, SessionOutcome
from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind

DEFAULT_INPUT_COST_PER_1K = 0.003
DEFAULT_OUTPUT_COST_PER_1K = 0.015


class EfficiencyEvaluator(MetricCalculator):
    """效率评测器。"""

    name: ClassVar[str] = "efficiency"
    kind: ClassVar[MetricKind] = "efficiency"

    def __init__(
        self,
        input_cost_per_1k: float = DEFAULT_INPUT_COST_PER_1K,
        output_cost_per_1k: float = DEFAULT_OUTPUT_COST_PER_1K,
    ):
        self.input_cost_per_1k = input_cost_per_1k
        self.output_cost_per_1k = output_cost_per_1k

    def calculate(self, inp: MetricInput) -> MetricBundle:
        outcomes = [o for o in inp.outcomes if isinstance(o, SessionOutcome)]
        er = EfficiencyResult()
        ops = list(inp.execution.memory_ops) if inp.execution is not None else []
        writes, searches = self._op_latencies(ops, MEMORY_WRITE_OPS), self._op_latencies(ops, MEMORY_READ_OPS)
        er.write_latency_ms = sum(writes) / len(writes) if writes else 0.0
        er.retrieval_latency_ms = sum(searches) / len(searches) if searches else 0.0
        er.tokens_in = sum(o.tokens_in for o in outcomes)
        er.tokens_out = sum(o.tokens_out for o in outcomes)
        er.cost_usd = (
            er.tokens_in / 1000 * self.input_cost_per_1k + er.tokens_out / 1000 * self.output_cost_per_1k
        )
        er.details = [
            {
                "write_ops": sum(op.op in MEMORY_WRITE_OPS for op in ops),
                "search_ops": sum(op.op in MEMORY_READ_OPS for op in ops),
                "avg_write_latency_ms": er.write_latency_ms,
                "avg_retrieval_latency_ms": er.retrieval_latency_ms,
                "cost_breakdown": {
                    "input": er.tokens_in / 1000 * self.input_cost_per_1k,
                    "output": er.tokens_out / 1000 * self.output_cost_per_1k,
                },
            }
        ]
        return MetricBundle(
            name=self.name,
            kind=self.kind,
            values={
                "write_latency_ms": er.write_latency_ms,
                "retrieval_latency_ms": er.retrieval_latency_ms,
                "tokens_in": float(er.tokens_in),
                "tokens_out": float(er.tokens_out),
                "cost_usd": er.cost_usd,
            },
            details=er.details,
        )

    @staticmethod
    def _op_latencies(ops: list[MemoryOp], kinds: frozenset[str]) -> list[float]:
        latencies: list[float] = []
        by_session: dict[int, list[float]] = {}
        for item in ops:
            if item.op in kinds and item.timestamp > 0:
                by_session.setdefault(item.session_id, []).append(item.timestamp)
        for ts_list in by_session.values():
            ts_list.sort()
            for prev, cur in pairwise(ts_list):
                latencies.append((cur - prev) * 1000)
        return latencies


EfficiencyCalculator = EfficiencyEvaluator
