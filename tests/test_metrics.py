"""测试：Utility / Efficiency 评测器。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.execution.executor import SessionOutcome
from dumemeval.metrics.dimensions.efficiency import EfficiencyEvaluator
from dumemeval.metrics.dimensions.utility import UtilityEvaluator
from dumemeval.models import EvalResult, MemoryOp


def _outcome(session_id: int, success: bool) -> SessionOutcome:
    return SessionOutcome(session_id=session_id, success=success)


class TestUtilityEvaluator:
    def test_all_success(self) -> None:
        result = EvalResult(task_name="t", memory_backend="m")
        ur = UtilityEvaluator().evaluate(result, [_outcome(1, True), _outcome(2, True)])
        assert ur.task_success is True
        assert ur.success_rate == 1.0
        assert ur.turns == 2

    def test_partial_success(self) -> None:
        result = EvalResult(task_name="t", memory_backend="m")
        ur = UtilityEvaluator().evaluate(result, [_outcome(1, True), _outcome(2, False)])
        assert ur.task_success is False
        assert ur.success_rate == 0.5

    def test_empty_outcomes(self) -> None:
        result = EvalResult(task_name="t", memory_backend="m")
        ur = UtilityEvaluator().evaluate(result, [])
        assert ur.success_rate == 0.0
        assert ur.turns == 0

    def test_memory_conditioned_gain(self) -> None:
        result = EvalResult(task_name="t", memory_backend="m")
        baseline = EvalResult(task_name="t", memory_backend="m-baseline")
        baseline.utility.success_rate = 0.3
        ur = UtilityEvaluator().evaluate(
            result, [_outcome(1, True), _outcome(2, True)], baseline_result=baseline
        )
        assert ur.memory_conditioned_gain == 0.7


class TestEfficiencyEvaluator:
    def test_counts_ops(self) -> None:
        result = EvalResult(task_name="t", memory_backend="m")
        result.memory_ops = [
            MemoryOp(session_id=1, op="add", content="x"),
            MemoryOp(session_id=1, op="search", query="q"),
            MemoryOp(session_id=2, op="add", content="y"),
        ]
        er = EfficiencyEvaluator().evaluate(result)
        assert er.details[0]["write_ops"] == 2
        assert er.details[0]["search_ops"] == 1

    def test_empty_ops(self) -> None:
        result = EvalResult(task_name="t", memory_backend="m")
        er = EfficiencyEvaluator().evaluate(result)
        assert er.details[0]["write_ops"] == 0

    def test_latency_from_timestamps(self) -> None:
        """同 session 内相邻 op timestamp 差 → latency。"""
        result = EvalResult(task_name="t", memory_backend="m")
        result.memory_ops = [
            MemoryOp(session_id=1, op="add", content="a", timestamp=100.0),
            MemoryOp(session_id=1, op="add", content="b", timestamp=100.5),
            MemoryOp(session_id=1, op="add", content="c", timestamp=101.0),
        ]
        er = EfficiencyEvaluator().evaluate(result)
        # 差值为 500ms 和 500ms → 平均 500ms
        assert er.write_latency_ms == 500.0

    def test_tokens_aggregated(self) -> None:
        """tokens 从 SessionOutcome 聚合。"""
        result = EvalResult(task_name="t", memory_backend="m")
        outcomes = [
            SessionOutcome(session_id=1, success=True, tokens_in=100, tokens_out=50),
            SessionOutcome(session_id=2, success=True, tokens_in=200, tokens_out=100),
        ]
        er = EfficiencyEvaluator().evaluate(result, outcomes)
        assert er.tokens_in == 300
        assert er.tokens_out == 150

    def test_cost_estimated(self) -> None:
        """cost 从 tokens 按单价估算。"""
        result = EvalResult(task_name="t", memory_backend="m")
        outcomes = [SessionOutcome(session_id=1, success=True, tokens_in=1000, tokens_out=1000)]
        er = EfficiencyEvaluator().evaluate(result, outcomes)
        # 1000 输入 * 0.003/1K + 1000 输出 * 0.015/1K = 0.003 + 0.015 = 0.018
        assert abs(er.cost_usd - 0.018) < 1e-9
