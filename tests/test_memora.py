"""测试：Memora 适配（FAMA 遗忘感知指标）。"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.memora import MemoraAdapter, MemoraData
from dumemeval.metrics.benchmarks.memora import fama_score
from dumemeval.models import AgentOutput, EvalResult
from dumemeval.verifier.base import Verdict

RAW = [
    {
        "question_id": "q1",
        "question": "What are the remaining todos?",
        "memory_evidence": {"remaining_tasks": ["Organize home office"]},
        "evaluation": {
            "evaluation_questions": [
                {
                    "evaluation_question_id": "e0",
                    "evaluation_question": "Does the response mention the task: Organize home office?",
                    "expected_answer": "yes",
                    "evaluation_type": "memory_presence",
                },
                {
                    "evaluation_question_id": "e1",
                    "evaluation_question": "Is 'Plan research time' listed as a remaining todo?",
                    "expected_answer": "no",
                    "evaluation_type": "forgetting_absence",
                },
            ]
        },
        "task": "remembering",
    },
    {
        "question_id": "q2",
        "question": "Recommend a plan.",
        "memory_evidence": {},
        "evaluation": {
            "evaluation_questions": [
                {
                    "evaluation_question_id": "e2",
                    "evaluation_question": "Does the response mention the plan?",
                    "expected_answer": "yes",
                    "evaluation_type": "memory_presence",
                },
            ]
        },
        "task": "recommending",
    },
]


class TestMemoraFama:
    def test_fama_formula(self) -> None:
        # MPA=1, FAA=1 → λ(1-1)=0 → FAMA=1
        assert fama_score(1, 1, 1, 1) == 1.0
        # MPA=1, FAA=0, λ=0.5 → 1 - 0.5*1 = 0.5
        assert fama_score(1, 1, 0, 1) == pytest.approx(0.5)
        # 全错 → 0
        assert fama_score(0, 1, 0, 1) == 0.0
        # 无 forgetting 子题 → λ=0 → FAMA=MPA
        assert fama_score(1, 1, 0, 0) == 1.0
        # 全空 → 0
        assert fama_score(0, 0, 0, 0) == 0.0


class TestMemoraAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("memora")
        data = MemoraData.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 2
        t = tasks[0]
        assert t.benchmark == "memora"
        assert len(t.sessions) == 2

    def test_evaluate_fama(self) -> None:
        # judge 按子题预期回答：mention 开头 → 是；否则 → 否
        a = MemoraAdapter(judge=lambda pred, sub_q, q: sub_q.startswith("Does the response mention"))
        task = a.build_tasks(MemoraData.from_raw(RAW))[0]
        qas = task.data["questions"]
        outputs = [AgentOutput(query=qas[0]["question"], output="Organize home office")]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        # q1: MPA=1 FAA=1 → FAMA=1
        assert metrics["fama"] == pytest.approx(100.0)
        assert metrics["fama_remembering"] == pytest.approx(100.0)

    def test_evaluate_partial_fama(self) -> None:
        # judge 恒真：presence 对（expected=yes）、forgetting 错（expected=no 但判 yes）
        def judge(pred: str, sub_q: str, q: str) -> bool:
            return True

        a = MemoraAdapter(judge=judge)
        task = a.build_tasks(MemoraData.from_raw(RAW))[0]
        qas = task.data["questions"]
        outputs = [AgentOutput(query=qas[0]["question"], output="Organize home office")]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        # MPA=1, FAA=0, λ=0.5 → FAMA=0.5 → *100=50
        assert metrics["fama"] == pytest.approx(50.0)

    def test_no_judge_falls_back_to_llm(self) -> None:
        a = get_benchmark("memora")
        task = a.build_tasks(MemoraData.from_raw(RAW))[0]
        qas = task.data["questions"]
        outputs = [AgentOutput(query=qas[0]["question"], output="Organize home office")]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify") as mock_verify:
            # LLM judge 恒判 yes：presence 对、forgetting 错 → MPA=1 FAA=0 → FAMA=0.5
            mock_verify.return_value = Verdict(label="yes", score=1.0, reason="ok")
            metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert mock_verify.call_count == 2  # 2 个子题各调一次
        assert metrics["fama"] == pytest.approx(50.0)

    def test_load_real_data(self) -> None:
        root = Path("/Users/yueqi/Coding/Agent/Memroy/Dataset/benchmarks/conversation/Memora/data")
        if not (root / "weekly").exists():
            pytest.skip("Memora 数据不在本地")
        data = MemoraData.load_period_dir(root, "weekly")
        assert len(data.questions) > 0
        assert all(q.task in {"remembering", "reasoning", "recommending"} for q in data.questions)


class TestMemoraEmptyOutput:
    def test_empty_pred_returns_empty_string(self) -> None:
        """空 pred 判分返回 ""（不等于 yes/no，恒判错）——旧实现返回 "no"
        会把 expected=no 的 forgetting 子题判对（FAA 虚高）。"""
        from dumemeval.metrics.benchmarks.memora import MemoraCalculator

        calc = MemoraCalculator(judge=lambda p, g, q: True)
        assert calc._judge_yes_no("", "sub", "q") == ""
        assert calc._judge_yes_no("text", "sub", "q") == "yes"

    def test_empty_output_zero_fama_no_judge_calls(self) -> None:
        """空 output → 全部子题判错（MPA=FAA=0 → FAMA=0），不调 judge。"""
        a = MemoraAdapter()
        data = MemoraData.from_raw(RAW)
        task = a.build_tasks(data)[0]
        outputs = [AgentOutput(query=task.data["questions"][0]["question"], output="")]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify") as mock_verify:
            metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert mock_verify.call_count == 0
        assert metrics["fama"] == pytest.approx(0.0)
