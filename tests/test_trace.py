"""测试：Trace 维度（agent 行为体检）——业务问题「trace 是否正规」。"""

from __future__ import annotations

from dumemeval.metrics import MetricInput, TraceCalculator
from dumemeval.models import MemoryOp, SessionOutcome, TaskExecution


def _execution(outcomes: list[dict[str, object]], ops: list[MemoryOp] | None = None) -> TaskExecution:
    return TaskExecution(
        task_id="t",
        task_name="t",
        memory_backend="m",
        sessions=[SessionOutcome.model_validate(item) for item in outcomes],
        memory_ops=ops or [],
    )


class TestTraceCalculator:
    def test_healthy_trace_all_green(self) -> None:
        bundle = TraceCalculator().calculate(
            MetricInput(
                execution=_execution(
                    [
                        {"session_id": 1, "success": True, "observation": "bought B001", "error": None},
                        {"session_id": 2, "success": True, "observation": "used memory", "error": None},
                    ],
                    ops=[
                        MemoryOp(session_id=1, op="add", content="pref"),
                        MemoryOp(session_id=2, op="search"),
                    ],
                )
            )
        )
        assert bundle.kind == "trace"
        assert bundle.values["trace_captured_rate"] == 1.0
        assert bundle.values["empty_output_rate"] == 0.0
        assert bundle.values["error_rate"] == 0.0
        assert bundle.values["memory_write_ops"] == 1.0
        assert bundle.values["memory_read_ops"] == 1.0
        assert bundle.values["memory_tool_used"] == 1.0

    def test_empty_output_detected(self) -> None:
        """observation 空 = 没采集到 agent 输出，依赖输出的指标会假 0。"""
        bundle = TraceCalculator().calculate(
            MetricInput(
                execution=_execution(
                    [
                        {"session_id": 1, "success": True, "observation": "", "error": None},
                        {"session_id": 2, "success": True, "observation": "ok", "error": None},
                    ]
                )
            )
        )
        assert bundle.values["empty_output_rate"] == 0.5
        assert bundle.values["trace_captured_rate"] == 0.5

    def test_error_rate_counts_failed_sessions(self) -> None:
        bundle = TraceCalculator().calculate(
            MetricInput(
                execution=_execution(
                    [
                        {"session_id": 1, "success": False, "observation": "", "error": "boom"},
                        {"session_id": 2, "success": True, "observation": "ok", "error": None},
                    ]
                )
            )
        )
        assert bundle.values["error_rate"] == 0.5

    def test_no_memory_ops_flags_unused_memory(self) -> None:
        """memory 配了却一次没读写 → memory_tool_used=0（业务最关心的失败模式）。"""
        bundle = TraceCalculator().calculate(
            MetricInput(
                execution=_execution([{"session_id": 1, "success": True, "observation": "ok", "error": None}])
            )
        )
        assert bundle.values["memory_tool_used"] == 0.0
        assert bundle.values["memory_write_ops"] == 0.0

    def test_lifecycle_ops_do_not_count_as_agent_memory_use(self) -> None:
        """setup/inject/snapshot 是框架动作，不能算 agent 用了 memory。"""
        bundle = TraceCalculator().calculate(
            MetricInput(
                execution=_execution(
                    [{"session_id": 1, "success": True, "observation": "ok", "error": None}],
                    ops=[
                        MemoryOp(session_id=0, op="setup"),
                        MemoryOp(session_id=1, op="inject"),
                        MemoryOp(session_id=1, op="snapshot"),
                    ],
                )
            )
        )
        assert bundle.values["memory_tool_used"] == 0.0

    def test_no_sessions_is_zero_not_crash(self) -> None:
        bundle = TraceCalculator().calculate(MetricInput(execution=_execution([])))
        assert bundle.values["trace_captured_rate"] == 0.0
        assert bundle.values["error_rate"] == 0.0


class TestTraceInAggregator:
    def test_trace_flat_metrics_namespaced(self) -> None:
        from dumemeval.metrics import MetricsAggregator

        report = MetricsAggregator([TraceCalculator()]).run(
            MetricInput(
                execution=_execution([{"session_id": 1, "success": True, "observation": "ok", "error": None}])
            )
        )
        assert report.flat["trace.trace_captured_rate"] == 1.0
