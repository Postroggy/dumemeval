"""Trace 指标：agent 行为体检（业务问题「trace 是否正规」）。

数据源全部是已采集内容——TaskExecution.sessions（observation/error）+ memory_ops，
不引入新的探测通道。计算器只产出 bundle。
"""

from __future__ import annotations

from typing import Any, ClassVar

from ...models import MEMORY_READ_OPS, MEMORY_WRITE_OPS, SessionOutcome, TraceResult
from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind


class TraceCalculator(MetricCalculator):
    """agent 行为体检计算器。"""

    name: ClassVar[str] = "trace"
    kind: ClassVar[MetricKind] = "trace"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        execution = inp.execution
        outcomes = execution.sessions if execution is not None else []
        ops = execution.memory_ops if execution is not None else []
        total = len(outcomes)

        captured = sum(1 for rec in outcomes if str(rec.observation or "").strip())
        errored = sum(1 for rec in outcomes if rec.error or not rec.success)

        writes = sum(1 for op in ops if op.op in MEMORY_WRITE_OPS)
        reads = sum(1 for op in ops if op.op in MEMORY_READ_OPS)

        captured_rate = captured / total if total else 0.0
        trace = TraceResult(
            trace_captured_rate=captured_rate,
            empty_output_rate=1.0 - captured_rate if total else 0.0,
            error_rate=errored / total if total else 0.0,
            memory_tool_used=True if writes or reads else None,
            memory_write_ops=writes or None,
            memory_read_ops=reads or None,
            details=self._details(outcomes),
        )

        values = {
            "trace_captured_rate": trace.trace_captured_rate,
            "empty_output_rate": trace.empty_output_rate,
            "error_rate": trace.error_rate,
        }
        for name in ("memory_tool_used", "memory_write_ops", "memory_read_ops"):
            value = getattr(trace, name)
            if value is not None:
                values[name] = float(value)
        return MetricBundle(
            name=self.name,
            kind=self.kind,
            values=values,
            details=[
                *trace.details,
                {
                    "memory_observation": "positive evidence only; counts are lower bounds, absent evidence is unmeasured",
                    "sources": sorted(
                        {op.source for op in ops if op.op in MEMORY_WRITE_OPS | MEMORY_READ_OPS}
                    ),
                },
            ],
        )

    @staticmethod
    def _details(outcomes: list[SessionOutcome]) -> list[dict[str, Any]]:
        return [
            {
                "session_id": rec.session_id,
                "captured": bool(str(rec.observation or "").strip()),
                "success": rec.success,
                "error": rec.error,
            }
            for rec in outcomes
        ]
