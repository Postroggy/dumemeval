"""测试：LongMemEval 适配（LLM judge + abstention）。"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.longmemeval import LongMemEvalAdapter, LongMemEvalData
from dumemeval.metrics.benchmarks.longmemeval import build_anscheck_prompt, judge_yes
from dumemeval.models import AgentOutput, EvalResult
from dumemeval.verifier.base import Verdict

RAW = [
    {
        "question_id": "0a995998",
        "question_type": "single_hop",
        "question_content": {
            "facts": ["I got a pair of boots from Zara on February 5th."],
            "question": "What did I get from Zara?",
            "answer": "boots",
        },
    },
    {
        "question_id": "0862e8bf_abs",
        "question_type": "temp_reasoning_explicit",
        "question_content": {
            "facts": ["No relevant information."],
            "question": "When did I last visit Paris?",
            "answer": "Not enough information to determine.",
            "explanation": "The user never mentioned Paris.",
        },
    },
]


class TestLongMemEvalScoring:
    def test_judge_yes(self) -> None:
        assert judge_yes("yes") is True
        assert judge_yes("Yes, it matches.") is True
        assert judge_yes("no") is False

    def test_build_anscheck_prompt_normal(self) -> None:
        prompt = build_anscheck_prompt("single-session-user", "Q?", "A", "R")
        assert "Q?" in prompt and "A" in prompt and "R" in prompt
        assert "Is the model response correct? Answer yes or no only." in prompt

    def test_build_anscheck_prompt_temporal(self) -> None:
        prompt = build_anscheck_prompt("temporal-reasoning", "Q?", "18", "R")
        assert "off-by-one" in prompt

    def test_build_anscheck_prompt_abstention(self) -> None:
        prompt = build_anscheck_prompt("temp", "Q?", "exp", "R", abstention=True)
        assert "unanswerable" in prompt
        assert "Does the model correctly identify" in prompt


class TestLongMemEvalAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("longmemeval")
        data = LongMemEvalData.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 2
        t = tasks[0]
        assert t.benchmark == "longmemeval"
        assert len(t.sessions) == 2
        assert "Zara" in t.sessions[0].instruction

    def test_abstention_detected(self) -> None:
        data = LongMemEvalData.from_raw(RAW)
        assert data.questions[0].abstention is False
        assert data.questions[1].abstention is True

    def test_evaluate_accuracy_and_abstention(self) -> None:
        a = LongMemEvalAdapter(judge=lambda pred, gold, q: True)
        task = a.build_tasks(LongMemEvalData.from_raw(RAW))[0]
        qas = task.data["questions"]
        outputs = [AgentOutput(query=qas[0]["question"], output="boots")]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert metrics["accuracy"] == 1.0
        assert "abstention_accuracy" not in metrics.values  # 无 abstention 题

    def test_evaluate_with_abstention(self) -> None:
        a = LongMemEvalAdapter(judge=lambda pred, gold, q: True)
        task = a.build_tasks(LongMemEvalData.from_raw(RAW))[1]
        qas = task.data["questions"]
        outputs = [AgentOutput(query=qas[0]["question"], output="I don't have enough information")]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert metrics["abstention_accuracy"] == 1.0
        assert "accuracy" not in metrics.values  # 纯 abstention 题不计 overall

    def test_no_judge_falls_back_to_official_prompt(self) -> None:
        a = get_benchmark("longmemeval")
        task = a.build_tasks(LongMemEvalData.from_raw(RAW))[0]
        qas = task.data["questions"]
        outputs = [AgentOutput(query=qas[0]["question"], output="boots")]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify_with_prompt") as mock_verify:
            mock_verify.return_value = Verdict(label="", score=0.0, raw="yes")
            metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert metrics["accuracy"] == 1.0

    def test_load_real_data(self) -> None:
        path = Path(
            "/Users/yueqi/Coding/Agent/Memroy/Dataset/data/longmemeval_data/2_questions/0822_all_500_questions_final_v2.json"
        )
        if not path.exists():
            pytest.skip("LongMemEval 数据不在本地")
        data = LongMemEvalData.load_json(path)
        assert len(data.questions) == 500
        assert sum(1 for q in data.questions if q.abstention) == 30
