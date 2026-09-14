"""测试：Trace 维度（agent 行为体检）——业务问题「trace 是否正规」。"""

from __future__ import annotations

import pytest

from dumemeval.metrics import MetricInput, TraceCalculator
from dumemeval.models import EvalResult, MemoryOp


def _result(outcomes: list[dict[str, object]], ops: list[MemoryOp] | None = None) -> EvalResult:
    return EvalResult(
        task_name="t",
        memory_backend="m",
        session_outcomes=outcomes,
        memory_ops=ops or [],
    )


class TestTraceCalculator:
    def test_healthy_trace_all_green(self) -> None:
        result = _result(
            [
                {"session_id": 1, "success": True, "observation": "bought B001", "error": None},
                {"session_id": 2, "success": True, "observation": "used memory", "error": None},
            ],
            ops=[MemoryOp(session_id=1, op="add", content="pref"), MemoryOp(session_id=2, op="search")],
        )
        bundle = TraceCalculator().calculate(MetricInput(result=result))

        assert bundle.kind == "trace"
        assert bundle.values["trace_captured_rate"] == 1.0
        assert bundle.values["empty_output_rate"] == 0.0
        assert bundle.values["error_rate"] == 0.0
        assert bundle.values["memory_write_ops"] == 1.0
        assert bundle.values["memory_read_ops"] == 1.0
        assert bundle.values["memory_tool_used"] == 1.0

    def test_empty_output_detected(self) -> None:
        """observation 空 = 没采集到 agent 输出，依赖输出的指标会假 0。"""
        result = _result(
            [
                {"session_id": 1, "success": True, "observation": "", "error": None},
                {"session_id": 2, "success": True, "observation": "ok", "error": None},
            ]
        )
        bundle = TraceCalculator().calculate(MetricInput(result=result))
        assert bundle.values["empty_output_rate"] == 0.5
        assert bundle.values["trace_captured_rate"] == 0.5

    def test_error_rate_counts_failed_sessions(self) -> None:
        result = _result(
            [
                {"session_id": 1, "success": False, "observation": "", "error": "boom"},
                {"session_id": 2, "success": True, "observation": "ok", "error": None},
            ]
        )
        bundle = TraceCalculator().calculate(MetricInput(result=result))
        assert bundle.values["error_rate"] == 0.5

    def test_no_memory_ops_flags_unused_memory(self) -> None:
        """memory 配了却一次没读写 → memory_tool_used=0（业务最关心的失败模式）。"""
        result = _result([{"session_id": 1, "success": True, "observation": "ok", "error": None}])
        bundle = TraceCalculator().calculate(MetricInput(result=result))
        assert bundle.values["memory_tool_used"] == 0.0
        assert bundle.values["memory_write_ops"] == 0.0

    def test_lifecycle_ops_do_not_count_as_agent_memory_use(self) -> None:
        """setup/inject/snapshot 是框架动作，不能算 agent 用了 memory。"""
        result = _result(
            [{"session_id": 1, "success": True, "observation": "ok", "error": None}],
            ops=[
                MemoryOp(session_id=0, op="setup"),
                MemoryOp(session_id=1, op="inject"),
                MemoryOp(session_id=1, op="snapshot"),
            ],
        )
        bundle = TraceCalculator().calculate(MetricInput(result=result))
        assert bundle.values["memory_tool_used"] == 0.0

    def test_written_back_to_result(self) -> None:
        result = _result([{"session_id": 1, "success": True, "observation": "ok", "error": None}])
        TraceCalculator().calculate(MetricInput(result=result))
        assert result.trace is not None
        assert result.trace.trace_captured_rate == 1.0

    def test_no_sessions_is_zero_not_crash(self) -> None:
        bundle = TraceCalculator().calculate(MetricInput(result=_result([])))
        assert bundle.values["trace_captured_rate"] == 0.0
        assert bundle.values["error_rate"] == 0.0


class TestTraceInAggregator:
    def test_trace_flat_metrics_namespaced(self) -> None:
        from dumemeval.metrics import MetricsAggregator

        result = _result([{"session_id": 1, "success": True, "observation": "ok", "error": None}])
        MetricsAggregator([TraceCalculator()]).run(MetricInput(result=result))
        assert result.metrics["trace.trace_captured_rate"] == pytest.approx(1.0)
