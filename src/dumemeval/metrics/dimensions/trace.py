"""Trace 指标：agent 行为体检（业务问题「trace 是否正规」）。

数据源全部是已采集内容——session_outcomes（observation/error）+ memory_ops，
不引入新的探测通道。

bundle 写回逻辑（``apply_trace``）在 ``core/base.py``，与其它维度的回写同处。
"""

from __future__ import annotations

from typing import Any, ClassVar

from ...models import TraceResult
from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind

# agent 侧 memory 读写（setup/inject/snapshot 是框架动作，不计入）
_WRITE_OPS = frozenset({"add", "replace", "remove", "delete"})
_READ_OPS = frozenset({"search", "query", "retrieve"})


class TraceCalculator(MetricCalculator):
    """agent 行为体检计算器。"""

    name: ClassVar[str] = "trace"
    kind: ClassVar[MetricKind] = "trace"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        execution = inp.execution
        outcomes = execution.sessions
        total = len(outcomes)

        captured = sum(1 for rec in outcomes if str(rec.observation or "").strip())
        errored = sum(1 for rec in outcomes if rec.error or not rec.success)

        writes = sum(1 for op in execution.memory_ops if op.op in _WRITE_OPS)
        reads = sum(1 for op in execution.memory_ops if op.op in _READ_OPS)

        captured_rate = captured / total if total else 0.0
        trace = TraceResult(
            trace_captured_rate=captured_rate,
            empty_output_rate=1.0 - captured_rate if total else 0.0,
            error_rate=errored / total if total else 0.0,
            memory_tool_used=bool(writes or reads),
            memory_write_ops=writes,
            memory_read_ops=reads,
            details=self._details(outcomes),
        )

        return MetricBundle(
            name=self.name,
            kind=self.kind,
            values={
                "trace_captured_rate": trace.trace_captured_rate,
                "empty_output_rate": trace.empty_output_rate,
                "error_rate": trace.error_rate,
                "memory_tool_used": 1.0 if trace.memory_tool_used else 0.0,
                "memory_write_ops": float(writes),
                "memory_read_ops": float(reads),
            },
            details=trace.details,
        )

    @staticmethod
    def _details(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "session_id": rec.session_id,
                "captured": bool(str(rec.observation or "").strip()),
                "success": rec.success,
                "error": rec.error,
            }
            for rec in outcomes
        ]
