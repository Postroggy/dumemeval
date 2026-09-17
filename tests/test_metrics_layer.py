"""测试：统一 metrics 层（协议 / 聚合器 / 官方 LoCoMo F1 / MemoryArena judgement_mode）。"""

import sys
from pathlib import Path
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.execution.executor import SessionOutcome
from dumemeval.metrics import (
    EfficiencyCalculator,
    MetricInput,
    MetricsAggregator,
    QualityCalculator,
    UtilityCalculator,
    calculator_names,
    get_benchmark_calculator,
    register_calculator,
)
from dumemeval.metrics.benchmarks.locomo import locomo_f1, locomo_f1_multi, score_locomo_f1
from dumemeval.metrics.benchmarks.memoryarena import judge_round
from dumemeval.models import AgentOutput, EvalTask, MemoryFact, MemoryOp, TaskExecution


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


class TestLocomoOfficialF1:
    def test_normalize_strips_articles_and_punctuation(self) -> None:
        assert locomo_f1("The LATTE.", "latte") == 1.0
        assert locomo_f1("a window seat", "window seat") == 1.0

    def test_stemmer_plurals(self) -> None:
        assert locomo_f1("window seats", "window seat") == 1.0

    def test_counter_not_set(self) -> None:
        """多重集合：重复 token 不能无限匹配。"""
        assert locomo_f1("latte latte", "latte") < 1.0

    def test_multi_answer_category_1(self) -> None:
        score = locomo_f1_multi("alice, bob", "Alice, Bob")
        assert score == 1.0

    def test_category_3_uses_text_before_semicolon(self) -> None:
        assert score_locomo_f1("paris", "Paris; also Lyon", category=3) == 1.0

    def test_category_5_refusal(self) -> None:
        assert score_locomo_f1("no information available", "x", category=5) == 1.0
        assert score_locomo_f1("alice likes tea", "x", category=5) == 0.0
        assert score_locomo_f1("no record of Caroline participating", "x", category=5) == 1.0

    def test_cjk_mixed_extracts_latin_for_f1(self) -> None:
        """中英混答时抽出括号/拉丁片段再走官方 F1。"""
        assert score_locomo_f1("心理健康（mental health）", "mental health", category=4) == 1.0
        assert score_locomo_f1("领养机构（adoption agencies）", "Adoption agencies", category=1) == 1.0


class TestMemoryArenaJudgement:
    @staticmethod
    def _plan_output() -> str:
        """官方 `=== Name's Plan ===` 结构输出。"""
        return "=== Eric's Plan ===\nDay 1:\ntransportation: Flight F1"

    def test_slot_match_success(self) -> None:
        judged = judge_round(
            self._plan_output(),
            {"days": 1, "transportation": "Flight F1"},
            name="Eric",
            judgement_mode="hint",
        )
        assert judged["success"] is True
        assert judged["judgement_mode"] == "hint"
        assert "Feedback for Eric" in judged["judgement"]

    def test_unstructured_output_fails(self) -> None:
        """无官方结构的裸文本判败（不做 GT 反向兜底——旧行为自证循环虚高）。"""
        judged = judge_round(
            "Flight F1",
            {"days": 1, "transportation": "Flight F1"},
            name="Eric",
            judgement_mode="hint",
        )
        assert judged["success"] is False

    def test_hint_vs_answer_text(self) -> None:
        gt = {"days": 1, "transportation": "Flight F1", "current_city": "NYC"}
        hint = judge_round("wrong", gt, name="Eric", judgement_mode="hint")
        answer = judge_round("wrong", gt, name="Eric", judgement_mode="answer")
        assert hint["success"] is False
        assert answer["success"] is False
        assert "slots need correction" in hint["judgement"]
        assert "Possible answer for Eric" in answer["judgement"]
        assert "Transportation: Flight F1" in answer["judgement"]

    def test_none_mode_has_no_feedback(self) -> None:
        judged = judge_round(
            self._plan_output(),
            {"days": 1, "transportation": "Flight F1"},
            judgement_mode="none",
        )
        assert judged["success"] is True
        assert judged["judgement"] == ""


class TestAggregator:
    def test_one_eval_one_flat_report(self) -> None:
        outcomes = [
            SessionOutcome(session_id=1, success=True, tokens_in=100, tokens_out=50),
            SessionOutcome(session_id=2, success=True, tokens_in=100, tokens_out=50),
        ]
        execution = _execution(
            sessions=outcomes,
            ops=[
                MemoryOp(session_id=1, op="add", content="a", timestamp=100.0),
                MemoryOp(session_id=1, op="add", content="b", timestamp=100.5),
            ],
        )
        task = EvalTask(
            name="t",
            data={
                "qa": [
                    {"question": "drink?", "answer": "latte", "category": 1},
                    {"question": "when?", "answer": "monday", "category": 2},
                ]
            },
            benchmark="locomo",
        )
        outputs = [
            AgentOutput(query="drink?", output="latte"),
            AgentOutput(query="when?", output="monday"),
        ]
        aggregated = MetricsAggregator(
            [
                QualityCalculator({"type": "rule"}),
                UtilityCalculator(),
                EfficiencyCalculator(),
            ]
        ).run(
            MetricInput(
                task=task,
                execution=execution,
                outputs=outputs,
                memory_files={"m.md": "latte monday"},
                ground_truth_facts=[MemoryFact(fact="latte"), MemoryFact(fact="monday")],
            )
        )
        assert aggregated.bundle("quality") is not None
        assert aggregated.bundle("utility") is not None
        assert aggregated.bundle("efficiency") is not None
        benchmark = CalculatorBenchmarkScorer("locomo", judge=lambda p, g, q: p.lower() == g.lower()).score(
            MetricInput(task=task, execution=execution, outputs=outputs)
        )
        assert benchmark.benchmark == "locomo"
        assert aggregated.flat["quality.recall"] == 1.0
        assert aggregated.flat["utility.success_rate"] == 1.0
        assert aggregated.flat["efficiency.tokens_in"] == 200.0
        assert benchmark.values["f1"] == 1.0
        assert benchmark.values["accuracy_multi_hop"] == 1.0
        assert benchmark.values["accuracy_temporal_reasoning"] == 1.0
        assert benchmark.benchmark == "locomo"

    def test_unknown_benchmark_calculator(self) -> None:
        with pytest.raises(ValueError, match="Unknown benchmark calculator"):
            get_benchmark_calculator("nope")

    def test_official_aliases_still_resolve(self) -> None:
        assert get_benchmark_calculator("memoryarena").name == "memoryarena_travel"
        assert get_benchmark_calculator("memdaily").name == "memsim"

    def test_llm_config_passthrough_to_calculator(self) -> None:
        from dumemeval.metrics.benchmarks.locomo import LoCoMoCalculator

        calc = get_benchmark_calculator("locomo", llm_config={"model": "DeepSeek-V4-Flash", "num_runs": 3})
        assert isinstance(calc, LoCoMoCalculator)
        assert calc._llm_config == {"model": "DeepSeek-V4-Flash", "num_runs": 3}

    def test_register_calculator_is_the_extension_point(self) -> None:
        """社区加数据集：register_calculator 后 get_benchmark_calculator 即可创建，无需改 if/elif。"""
        from dumemeval.metrics.core.base import MetricBundle, MetricCalculator, MetricKind

        class _ToyCalculator(MetricCalculator):
            name: ClassVar[str] = "toy_contrib"
            kind: ClassVar[MetricKind] = "benchmark"

            def calculate(self, inp: MetricInput) -> MetricBundle:
                return MetricBundle(name=self.name, kind=self.kind, values={"score": 1.0})

        register_calculator(_ToyCalculator)
        try:
            calc = get_benchmark_calculator("toy_contrib")
            assert calc.name == "toy_contrib"
            assert "toy_contrib" in calculator_names()
        finally:
            from dumemeval.metrics.core import registry as _reg

            _reg._REGISTRY.pop("toy_contrib", None)

    def test_declared_metric_names_use_classvar(self) -> None:
        from dumemeval.evaluation import declared_metric_names

        assert declared_metric_names("memoryarena_shopping") == [
            "match_ground_truth",
            "overall_success",
            "attribute_match",
        ]
        assert declared_metric_names("nope") == []
