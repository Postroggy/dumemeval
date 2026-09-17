"""测试：Utility / Efficiency 评测器。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.execution.executor import SessionOutcome
from dumemeval.metrics.core.base import MetricInput
from dumemeval.metrics.dimensions.efficiency import EfficiencyEvaluator
from dumemeval.metrics.dimensions.utility import UtilityEvaluator
from dumemeval.models import MemoryOp, TaskExecution


def _outcome(session_id: int, success: bool) -> SessionOutcome:
    return SessionOutcome(session_id=session_id, success=success)


def _execution(
    *, sessions: list[SessionOutcome] | None = None, ops: list[MemoryOp] | None = None
) -> TaskExecution:
    return TaskExecution(
        task_id="t",
        task_name="t",
        memory_backend="m",
        sessions=sessions or [],
        memory_ops=ops or [],
    )


class TestUtilityEvaluator:
    def test_all_success(self) -> None:
        bundle = UtilityEvaluator().calculate(
            MetricInput(execution=_execution(sessions=[_outcome(1, True), _outcome(2, True)]))
        )
        assert bundle.values["task_success"] == 1.0
        assert bundle.values["success_rate"] == 1.0
        assert bundle.values["turns"] == 2.0

    def test_partial_success(self) -> None:
        bundle = UtilityEvaluator().calculate(
            MetricInput(execution=_execution(sessions=[_outcome(1, True), _outcome(2, False)]))
        )
        assert bundle.values["task_success"] == 0.0
        assert bundle.values["success_rate"] == 0.5

    def test_empty_outcomes(self) -> None:
        bundle = UtilityEvaluator().calculate(MetricInput(execution=_execution()))
        assert bundle.values["success_rate"] == 0.0
        assert bundle.values["turns"] == 0.0

    def test_memory_conditioned_gain(self) -> None:
        bundle = UtilityEvaluator().calculate(
            MetricInput(
                execution=_execution(sessions=[_outcome(1, True), _outcome(2, True)]),
                extra={"baseline_success_rate": 0.3},
            )
        )
        assert bundle.values["memory_conditioned_gain"] == 0.7


class TestEfficiencyEvaluator:
    def test_counts_ops(self) -> None:
        bundle = EfficiencyEvaluator().calculate(
            MetricInput(
                execution=_execution(
                    ops=[
                        MemoryOp(session_id=1, op="add", content="x"),
                        MemoryOp(session_id=1, op="search", query="q"),
                        MemoryOp(session_id=2, op="add", content="y"),
                    ]
                )
            )
        )
        assert bundle.details[0]["write_ops"] == 2
        assert bundle.details[0]["search_ops"] == 1

    def test_replace_counts_as_write(self) -> None:
        """框架词表：replace 是写入，不是产品 API 名。"""
        bundle = EfficiencyEvaluator().calculate(
            MetricInput(
                execution=_execution(
                    ops=[
                        MemoryOp(session_id=1, op="replace", content="x"),
                        MemoryOp(session_id=1, op="search", query="q"),
                    ]
                )
            )
        )
        assert bundle.details[0]["write_ops"] == 1
        assert bundle.details[0]["search_ops"] == 1

    def test_empty_ops(self) -> None:
        bundle = EfficiencyEvaluator().calculate(MetricInput(execution=_execution()))
        assert bundle.details[0]["write_ops"] == 0

    def test_latency_from_timestamps(self) -> None:
        """同 session 内相邻 op timestamp 差 → latency。"""
        bundle = EfficiencyEvaluator().calculate(
            MetricInput(
                execution=_execution(
                    ops=[
                        MemoryOp(session_id=1, op="add", content="a", timestamp=100.0),
                        MemoryOp(session_id=1, op="add", content="b", timestamp=100.5),
                        MemoryOp(session_id=1, op="add", content="c", timestamp=101.0),
                    ]
                )
            )
        )
        assert bundle.values["write_latency_ms"] == 500.0

    def test_tokens_aggregated(self) -> None:
        """tokens 从 SessionOutcome 聚合。"""
        bundle = EfficiencyEvaluator().calculate(
            MetricInput(
                execution=_execution(
                    sessions=[
                        SessionOutcome(session_id=1, success=True, tokens_in=100, tokens_out=50),
                        SessionOutcome(session_id=2, success=True, tokens_in=200, tokens_out=100),
                    ]
                )
            )
        )
        assert bundle.values["tokens_in"] == 300.0
        assert bundle.values["tokens_out"] == 150.0

    def test_cost_estimated(self) -> None:
        """cost 从 tokens 按单价估算。"""
        bundle = EfficiencyEvaluator().calculate(
            MetricInput(
                execution=_execution(
                    sessions=[SessionOutcome(session_id=1, success=True, tokens_in=1000, tokens_out=1000)]
                )
            )
        )
        assert abs(bundle.values["cost_usd"] - 0.018) < 1e-9
