"""测试：ScriptMem 适配（确定性 MCQ：single/multi/ordering）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.scriptmem import ScriptMemAdapter
from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.metrics.benchmarks.scriptmem import (
    gold_letters,
    predicted_letters,
    score_item,
)
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput, SampleResult

RAW = [
    {
        "qa_id": "conv0#q0",
        "conversation_id": "conv-0",
        "qa_type": "single_choice",
        "question": "What is the inference?\n\nA. Option A\nB. Option B\nC. Option C",
        "answer": "B. Option B",
        "answer_letters": ["B"],
    },
    {
        "qa_id": "conv0#q1",
        "conversation_id": "conv-0",
        "qa_type": "multi_select",
        "question": "Which apply?\n\nA. One\nB. Two\nC. Three",
        "answer": ["A. One", "C. Three"],
        "answer_letters": ["A", "C"],
    },
    {
        "qa_id": "conv0#q2",
        "conversation_id": "conv-0",
        "qa_type": "ordering",
        "question": "Order the events.\n\nA. First\nB. Second\nC. Third",
        "answer": ["C. Third", "A. First", "B. Second"],
        "answer_letters": ["C", "A", "B"],
    },
]


class TestScriptMemScoring:
    def test_gold_letters(self) -> None:
        assert gold_letters("B. Option B") == ["B"]
        assert gold_letters(["A. One", "C. Three"]) == ["A", "C"]

    def test_single_choice(self) -> None:
        pred, malformed = predicted_letters("(B)", "single_choice")
        assert (pred, malformed) == (["B"], False)
        assert score_item("single_choice", ["B"], pred) == 1.0
        assert score_item("single_choice", ["B"], ["A"]) == 0.0

    def test_single_choice_boxed(self) -> None:
        pred, _ = predicted_letters(r"\boxed{B}", "single_choice")
        assert pred == ["B"]

    def test_multi_select(self) -> None:
        pred, malformed = predicted_letters("(A, C)", "multi_select")
        assert (pred, malformed) == (["A", "C"], False)
        assert score_item("multi_select", ["A", "C"], pred) == 1.0
        # 顺序无关
        assert score_item("multi_select", ["A", "C"], ["C", "A"]) == 1.0
        # 重复字母 malformed → 0
        assert score_item("multi_select", ["A", "C"], ["A", "A"], malformed=True) == 0.0

    def test_ordering(self) -> None:
        pred, malformed = predicted_letters("(C, A, B)", "ordering")
        assert (pred, malformed) == (["C", "A", "B"], False)
        assert score_item("ordering", ["C", "A", "B"], pred) == 1.0
        # 顺序不对 → 0
        assert score_item("ordering", ["C", "A", "B"], ["A", "B", "C"]) == 0.0

    def test_malformed_duplicate(self) -> None:
        pred, malformed = predicted_letters("(A, A)", "multi_select")
        assert malformed is True
        assert score_item("multi_select", ["A"], pred, malformed) == 0.0


class TestScriptMemAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("scriptmem")
        data = a.data_type.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "scriptmem"
        assert len(t.sessions) == 3
        assert t.sessions[0].query is not None
        assert t.sessions[0].query.startswith("What is the inference?")

    def test_evaluate_accuracy(self) -> None:
        a = get_benchmark("scriptmem")
        task = a.build_tasks(a.data_type.from_raw(RAW))[0]
        qas = task.data["qa"]
        outputs = [
            AgentOutput(query=qas[0]["question"], output="(B)"),
            AgentOutput(query=qas[1]["question"], output="(A, C)"),
            AgentOutput(query=qas[2]["question"], output="(C, A, B)"),
        ]
        result = CalculatorBenchmarkScorer("scriptmem").score(
            MetricInput(
                task=task,
                outputs=outputs,
                samples=[
                    SampleResult(sample_id=str(i), query=o.query, response=o.output)
                    for i, o in enumerate(outputs)
                ],
            )
        )
        assert result.values["accuracy"] == 1.0
        assert result.values["accuracy_single_choice"] == 1.0
        assert result.values["accuracy_multi_select"] == 1.0
        assert result.values["accuracy_ordering"] == 1.0

    def test_evaluate_partial(self) -> None:
        a = get_benchmark("scriptmem")
        task = a.build_tasks(a.data_type.from_raw(RAW))[0]
        qas = task.data["qa"]
        outputs = [
            AgentOutput(query=qas[0]["question"], output="(B)"),
            AgentOutput(query=qas[1]["question"], output="(A)"),  # 漏了 C
            AgentOutput(query=qas[2]["question"], output="(A, B, C)"),  # 顺序错
        ]
        result = CalculatorBenchmarkScorer("scriptmem").score(
            MetricInput(
                task=task,
                outputs=outputs,
                samples=[
                    SampleResult(sample_id=str(i), query=o.query, response=o.output)
                    for i, o in enumerate(outputs)
                ],
            )
        )
        assert result.values["accuracy"] == pytest.approx(1 / 3)
        assert result.values["accuracy_multi_select"] == 0.0
        assert result.values["accuracy_ordering"] == 0.0

    def test_load_real_public_questions(self) -> None:
        path = Path(
            "/Users/yueqi/Coding/Agent/Memroy/Dataset/benchmarks/conversation/ScriptMem/data/public/questions.jsonl"
        )
        if not path.exists():
            pytest.skip("ScriptMem 数据不在本地")
        data = ScriptMemAdapter.load_jsonl(path)
        assert len(data.qa) > 0
        assert all(q.qa_type in {"single_choice", "multi_select", "ordering"} for q in data.qa)
