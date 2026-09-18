"""测试：BenchmarkAdapter + LoCoMo + MemoryArena travel 适配。"""

import sys
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401  触发注册
from dumemeval.benchmarks.memoryarena.datasets.travel import MemoryArenaTravelAdapter, MemoryArenaTravelData
from dumemeval.datasets import benchmark_names, get_benchmark
from dumemeval.datasets.benchmarks.locomo import LoCoMoAdapter, LoCoMoData
from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.metrics.benchmarks.locomo import locomo_f1
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput


@pytest.fixture
def locomo_data() -> list[Any]:
    """LoCoMo 样例数据（2 个对话，每个 2 个 session + 3 个 QA）。"""
    return [
        {
            "sample_id": 0,
            "conversation": {
                "speaker_a": "Alice",
                "speaker_b": "Bob",
                "session_1": [
                    {"speaker": "Alice", "text": "I like latte without sugar"},
                    {"speaker": "Bob", "text": "Good to know"},
                ],
                "session_2": [
                    {"speaker": "Alice", "text": "I prefer window seats"},
                ],
            },
            "qa": [
                {"question": "What does Alice like to drink?", "answer": "latte", "category": 1},
                {"question": "Where does Alice prefer to sit?", "answer": "window seat", "category": 1},
                {"question": "Does Alice take sugar?", "answer": "no sugar", "category": 2},
            ],
        },
        {
            "sample_id": 1,
            "conversation": {
                "speaker_a": "Carol",
                "speaker_b": "Dave",
                "session_1": [{"speaker": "Carol", "text": "I travel to Shanghai often"}],
            },
            "qa": [{"question": "Where does Carol travel?", "answer": "Shanghai", "category": 1}],
        },
    ]


@pytest.fixture
def travel_data() -> list[Any]:
    """MemoryArena travel 样例（1 个 base_person + 2 个 interdependent rounds）。"""
    return [
        {
            "id": 0,
            "base_person": {
                "name": "Jennifer",
                "query": "I am Jennifer.\nPlease help me plan a trip from St. Petersburg.\nI prefer window seats.",
                "daily_plans": [],
            },
            "questions": [
                {"round_idx": 0, "name": "Eric", "query": "Plan day 1 transport."},
                {
                    "round_idx": 1,
                    "name": "Eric",
                    "query": "Plan day 2, considering Jennifer's window seat preference.",
                },
            ],
            "answers": [
                {"days": 1, "transportation": "Flight F1"},
                {"days": 2, "transportation": "Flight F2", "window_seat": True},
            ],
        }
    ]


class TestRegistry:
    def test_benchmark_names(self) -> None:
        names = benchmark_names()
        assert "locomo" in names
        assert "memoryarena_travel" in names
        assert "memoryarena_shopping" in names
        assert "memoryarena_search" in names
        assert "memoryarena_math" in names
        assert "memoryarena_phys" in names
        assert "streammembench" in names

    def test_get_benchmark(self) -> None:
        a = cast(LoCoMoAdapter, get_benchmark("locomo"))
        assert a.name == "locomo"
        assert a.name == "locomo"

    def test_unknown_benchmark_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown benchmark"):
            get_benchmark("bogus")


class TestLoCoMo:
    def test_from_raw_and_build(self, locomo_data: list[Any]) -> None:
        """raw → LoCoMoData（类型化）→ build_tasks。"""
        a = cast(LoCoMoAdapter, get_benchmark("locomo"))
        data = a.data_type.from_raw(locomo_data)
        assert isinstance(data, LoCoMoData)
        assert len(data.items) == 2

        tasks = a.build_tasks(data)
        assert len(tasks) == 2
        t = tasks[0]
        assert len(t.sessions) == 5  # 2 ingest + 3 QA
        assert "latte" in t.sessions[0].instruction
        assert t.sessions[-1].query == "Does Alice take sugar?"
        assert "A: latte" not in t.sessions[-1].instruction
        assert "latte" in t.memory_ground_truth
        assert t.benchmark == "locomo"

    def test_empty_data(self) -> None:
        a = cast(LoCoMoAdapter, get_benchmark("locomo"))
        data = a.data_type.from_raw([])
        assert a.build_tasks(data) == []

    def test_official_f1(self) -> None:
        assert locomo_f1("latte", "latte") == 1.0
        assert locomo_f1("The LATTE.", "latte") == 1.0
        assert locomo_f1("latte with sugar", "latte") > 0
        assert locomo_f1("tea", "latte") == 0.0

    def test_evaluate_metrics(self, locomo_data: list[Any]) -> None:
        """evaluate 返回官方 F1 + 按类 accuracy。"""
        a = cast(LoCoMoAdapter, get_benchmark("locomo"))
        data = a.data_type.from_raw(locomo_data)
        task = a.build_tasks(data)[0]
        outputs = [
            AgentOutput(query="What does Alice like to drink?", output="latte"),
            AgentOutput(query="Where does Alice prefer to sit?", output="window seat"),
            AgentOutput(query="Does Alice take sugar?", output="no sugar"),
        ]
        a._judge_correct = lambda pred, gold, question: pred.lower() == gold.lower()  # type: ignore[method-assign]
        metrics = CalculatorBenchmarkScorer("locomo", judge=lambda p, g, q: p.lower() == g.lower()).score(
            MetricInput(task=task, outputs=outputs)
        )
        assert metrics.benchmark == "locomo"
        assert metrics.values["accuracy"] == 1.0
        assert metrics.values["f1"] == 1.0
        assert metrics.by_category["multi_hop"]["accuracy"] == 1.0
        assert metrics.by_category["temporal_reasoning"]["accuracy"] == 1.0
        assert "multi_hop" in metrics.by_category
        assert "temporal_reasoning" in metrics.by_category

    def test_missing_prediction_counts_as_zero(self, locomo_data: list[Any]) -> None:
        a = cast(LoCoMoAdapter, get_benchmark("locomo"))
        data = a.data_type.from_raw(locomo_data)
        task = a.build_tasks(data)[0]
        a._judge_correct = lambda pred, gold, question: pred.lower() == gold.lower()  # type: ignore[method-assign]
        metrics = CalculatorBenchmarkScorer("locomo", judge=lambda p, g, q: p.lower() == g.lower()).score(
            MetricInput(
                task=task,
                outputs=[AgentOutput(query="What does Alice like to drink?", output="latte")],
            )
        )
        assert metrics.values["accuracy"] == pytest.approx(1 / 3)
        assert 0.0 < metrics.values["f1"] < 1.0


class TestMemoryArenaTravel:
    def test_from_raw_and_build(self, travel_data: list[Any]) -> None:
        a = cast(MemoryArenaTravelAdapter, get_benchmark("memoryarena_travel"))
        data = a.data_type.from_raw(travel_data)
        assert isinstance(data, MemoryArenaTravelData)

        tasks = a.build_tasks(data, flow="custom")
        assert len(tasks) == 1
        t = tasks[0]
        assert len(t.sessions) == 3
        assert "Jennifer" in t.sessions[0].instruction
        assert "window seats" in t.memory_ground_truth
        assert t.benchmark == "memoryarena_travel"

    def test_round_dependency(self, travel_data: list[Any]) -> None:
        a = cast(MemoryArenaTravelAdapter, get_benchmark("memoryarena_travel"))
        data = a.data_type.from_raw(travel_data)
        t = a.build_tasks(data, flow="custom")[0]
        assert "之前的回合信息" in t.sessions[2].instruction

    def test_evaluate_metrics(self, travel_data: list[Any]) -> None:
        """在线 slot 判定：`=== Plan ===` 结构 + transportation 真值 → derived_round_success=1.0。"""
        a = cast(MemoryArenaTravelAdapter, get_benchmark("memoryarena_travel"))
        data = a.data_type.from_raw(travel_data)
        task = a.build_tasks(data, flow="custom")[0]
        outputs = [
            AgentOutput(
                query="Plan day 1 transport.",
                output="=== Eric's Plan ===\nDay 1:\ntransportation: Flight F1",
            ),
            AgentOutput(
                query="Plan day 2, considering Jennifer's window seat preference.",
                output="=== Eric's Plan ===\nDay 2:\ntransportation: Flight F2",
            ),
        ]
        metrics = CalculatorBenchmarkScorer("memoryarena_travel").score(
            MetricInput(task=task, outputs=outputs)
        )
        assert metrics.values["derived_round_success"] == 1.0
        assert metrics.details[0]["judgement_mode"] == "hint"
        assert "Feedback for" in metrics.details[0]["judgement"]

    def test_unstructured_output_scores_zero(self, travel_data: list[Any]) -> None:
        """无官方结构的裸文本 → derived_round_success=0（旧 GT 反向兜底会自证虚高，已删）。"""
        a = cast(MemoryArenaTravelAdapter, get_benchmark("memoryarena_travel"))
        data = a.data_type.from_raw(travel_data)
        task = a.build_tasks(data, flow="custom")[0]
        outputs = [
            AgentOutput(query="Plan day 1 transport.", output="Flight F1"),
            AgentOutput(
                query="Plan day 2, considering Jennifer's window seat preference.",
                output="Flight F2 window seat",
            ),
        ]
        metrics = CalculatorBenchmarkScorer("memoryarena_travel").score(
            MetricInput(task=task, outputs=outputs)
        )
        assert metrics.values["derived_round_success"] == 0.0


class TestMemoryArenaShopping:
    def test_build_requires_webshop_actions(self) -> None:
        a = get_benchmark("memoryarena_shopping")
        data = a.data_type.from_raw(
            [
                {
                    "id": 0,
                    "questions": ["Buy cake mix"],
                    "answers": [{"target_asin": "B00TUDFEW2"}],
                    "category": "baking",
                }
            ]
        )
        task = a.build_tasks(data)[0]
        assert task.task_environment.get("type") == "webshop"
        # The task template describes the goal and evidence boundary. The selected
        # environment provider supplies action syntax through its runtime hint.
        assert "Buy cake mix" in task.sessions[0].instruction
        assert "通过任务环境提供的工具" in task.sessions[0].instruction
        assert "不要编造 ASIN" in task.sessions[0].instruction
