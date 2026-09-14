"""测试：PersonaMem 适配（官方 MCQ 字母匹配判分）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.personamem import PersonaMemAdapter, PersonaMemData
from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.metrics.benchmarks.personamem import extract_options, is_correct
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput, SampleResult

PERSONA_RAW = {
    "questions": [
        {
            "question_id": "q1",
            "question_type": "recall_user_shared_facts",
            "topic": "music",
            "user_question_or_message": "What music does the user like?",
            "correct_answer": "(c)",
            "all_options": ["(a) Jazz", "(b) Classical", "(c) Pop", "(d) Rock"],
            "shared_context_id": "ctx1",
            "end_index_in_shared_context": 100,
        },
        {
            "question_id": "q2",
            "question_type": "track_full_preference_evolution",
            "topic": "music",
            "user_question_or_message": "How has their taste evolved?",
            "correct_answer": "(a)",
            "all_options": ["(a) Pop to Jazz", "(b) Jazz to Pop", "(c) No change", "(d) Rock to Pop"],
            "shared_context_id": "ctx1",
        },
    ],
    "contexts": {
        "ctx1": "Current user persona: Name: Kanoa\nGender: Male\n\nUser: I like pop music.\nAssistant: Great choice!",
    },
}


class TestPersonaMemScoring:
    def test_extract_options_parens(self) -> None:
        assert extract_options("I think (c) is correct") == {"c"}
        assert extract_options("The answer is (a) and (d)") == {"a", "d"}

    def test_extract_options_bare(self) -> None:
        assert extract_options("answer: b") == {"b"}
        assert extract_options("I pick a") == {"a"}

    def test_is_correct_match(self) -> None:
        assert is_correct("The answer is (c)", "(c)") is True
        assert is_correct("c", "(c)") is True  # 裸字母
        assert is_correct("<final_answer> (a) </final_answer>", "(a)") is True

    def test_is_correct_wrong(self) -> None:
        assert is_correct("The answer is (b)", "(c)") is False
        assert is_correct("", "(c)") is False

    def test_official_sample(self) -> None:
        # 官方正确格式：只输出选项字母
        assert is_correct("(c)", "(c)") is True


class TestPersonaMemAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("personamem")
        data = PersonaMemData.from_raw(PERSONA_RAW)
        assert isinstance(data, PersonaMemData)
        assert len(data.questions) == 2

        tasks = a.build_tasks(data)
        assert len(tasks) == 1  # 同一个 context 合并成一个任务
        t = tasks[0]
        assert t.benchmark == "personamem"
        assert len(t.sessions) == 3  # 1 context 注入 + 2 问答
        assert "Kanoa" in t.sessions[0].instruction
        assert t.sessions[1].query == "What music does the user like?"

    def test_evaluate_accuracy(self) -> None:
        a = get_benchmark("personamem")
        task = a.build_tasks(PersonaMemData.from_raw(PERSONA_RAW))[0]
        outputs = [
            AgentOutput(query="What music does the user like?", output="(c)"),
            AgentOutput(query="How has their taste evolved?", output="(b)"),  # 错
        ]
        result = CalculatorBenchmarkScorer("personamem").score(
            MetricInput(
                task=task,
                outputs=outputs,
                samples=[
                    SampleResult(sample_id=str(i), query=o.query, response=o.output)
                    for i, o in enumerate(outputs)
                ],
            )
        )
        assert result.values["accuracy"] == pytest.approx(0.5)
        assert result.values["accuracy_recall_user_shared_facts"] == 1.0
        assert result.values["accuracy_track_full_preference_evolution"] == 0.0
        assert result.by_category["recall_user_shared_facts"]["count"] == 1.0

    def test_load_csv_real_data(self) -> None:
        """真实数据冒烟：能加载 CSV + contexts（不跑评测）。"""
        csv_path = Path("/Users/yueqi/Coding/Agent/Memroy/Dataset/data/PersonaMem/questions_32k.csv")
        ctx_path = Path("/Users/yueqi/Coding/Agent/Memroy/Dataset/data/PersonaMem/shared_contexts_32k.jsonl")
        if not csv_path.exists():
            pytest.skip("PersonaMem 数据不在本地")
        data = PersonaMemAdapter.load_csv(csv_path, ctx_path)
        assert len(data.questions) > 0
        assert len(data.contexts) > 0
        # all_options 两种格式都应解析
        assert all(q.all_options or not q.all_options for q in data.questions)
