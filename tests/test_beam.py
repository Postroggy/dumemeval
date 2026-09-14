"""测试：BEAM 适配（LLM judge rubric 打分）。"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.beam import BeamAdapter, BeamData
from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.metrics.benchmarks.beam import build_judge_prompt, parse_score
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput, SampleResult
from dumemeval.verifier.base import Verdict

RAW = [
    {
        "id": "100K-1-abstention-0",
        "question": "How did the user feedback influence the UI/UX improvements?",
        "context": "[March-15-2024] user: I'm working on a project.",
        "rubrics": [
            "Based on the provided chat, there is no information related to how user feedback influenced UI/UX."
        ],
        "question_type": "abstention",
        "ideal_response": "Based on the provided chat, there is no information...",
        "difficulty": "medium",
        "topic_id": "1",
        "chat_size": "100K",
    }
]


class TestBeamScoring:
    def test_parse_score(self) -> None:
        assert parse_score('{"score": 1.0}') == 1.0
        assert parse_score('{"score": 0.5}') == 0.5
        assert parse_score('{"score": 0.0}') == 0.0
        assert parse_score("garbage") is None

    def test_build_judge_prompt(self) -> None:
        prompt = build_judge_prompt("Q?", "rubric 1", "R")
        assert "Q?" in prompt and "rubric 1" in prompt and "R" in prompt
        assert "1.0 or 0.5 or 0.0" in prompt


class TestBeamAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("beam")
        data = BeamData.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "beam"
        assert len(t.sessions) == 2
        assert "project" in t.sessions[0].instruction

    def test_evaluate_with_judge(self) -> None:
        a = BeamAdapter(judge=lambda pred, rubric, q: True)
        task = a.build_tasks(BeamData.from_raw(RAW))[0]
        qas = task.data["samples"][0]
        outputs = [AgentOutput(query=qas["question"], output="no information available")]
        metrics = CalculatorBenchmarkScorer("beam", judge=lambda pred, rubric, q: True).score(
            MetricInput(
                task=task,
                outputs=outputs,
                samples=[SampleResult(sample_id="0", query=qas["question"], response=outputs[0].output)],
            )
        )
        assert metrics.values["llm_judge_score"] == 1.0
        assert metrics.values["llm_judge_score_abstention"] == 1.0

    def test_evaluate_no_judge_official_prompt(self) -> None:
        a = get_benchmark("beam")
        task = a.build_tasks(BeamData.from_raw(RAW))[0]
        qas = task.data["samples"][0]
        outputs = [AgentOutput(query=qas["question"], output="no info")]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify_with_prompt") as mock_verify:
            mock_verify.return_value = Verdict(label="", score=0.0, raw='{"score": 0.0}')
            metrics = CalculatorBenchmarkScorer("beam", judge=lambda pred, rubric, q: False).score(
                MetricInput(
                    task=task,
                    outputs=outputs,
                    samples=[SampleResult(sample_id="0", query=qas["question"], response=outputs[0].output)],
                )
            )
        assert metrics.values["llm_judge_score"] == 0.0

    def test_load_real_data(self) -> None:
        path = Path(
            "/Users/yueqi/Coding/Agent/Memroy/Dataset/benchmarks/conversation/BEAM/aml_input_beam.jsonl"
        )
        if not path.exists():
            pytest.skip("BEAM 数据不在本地")
        data = BeamData.load_jsonl(path)
        assert len(data.samples) == 400
        from collections import Counter

        types = Counter(s.question_type for s in data.samples)
        assert len(types) == 10
        assert all(v == 40 for v in types.values())


class TestEventOrdering:
    """官方 τ_b×F1 口径的确定性近似（修复：此前 event_ordering 冒充普通 rubric 分）。"""

    def test_kendall_tau_b(self) -> None:
        from dumemeval.metrics.benchmarks.beam import kendall_tau_b

        assert kendall_tau_b([0, 1, 2], [0, 1, 2]) == pytest.approx(1.0)
        assert kendall_tau_b([0, 1, 2], [2, 1, 0]) == pytest.approx(-1.0)

    def test_perfect_order_scores_one(self) -> None:
        from dumemeval.metrics.benchmarks.beam import event_ordering_score

        score, parts = event_ordering_score("1. alpha\n2. beta\n3. gamma", ["alpha", "beta", "gamma"])
        assert score == pytest.approx(1.0)
        assert parts["f1"] == pytest.approx(1.0)
        assert parts["tau_b"] == pytest.approx(1.0)

    def test_reversed_order_scores_zero(self) -> None:
        """完全倒序：官方 τ_norm=(τ+1)/2 → τ=-1 得 0（0.5 是部分无序的中间档）。"""
        from dumemeval.metrics.benchmarks.beam import event_ordering_score

        score, parts = event_ordering_score("1. gamma\n2. beta\n3. alpha", ["alpha", "beta", "gamma"])
        assert score == pytest.approx(0.0)
        assert parts["tau_b"] == pytest.approx(-1.0)
        assert parts["f1"] == pytest.approx(1.0)  # 事件全对齐，只是顺序反了

    def test_partial_disorder_between(self) -> None:
        """部分无序：τ 介于 ±1 之间 → 分数介于 0 与 1 之间。"""
        from dumemeval.metrics.benchmarks.beam import event_ordering_score

        score, _ = event_ordering_score("1. beta\n2. alpha\n3. gamma", ["alpha", "beta", "gamma"])
        assert 0.0 < score < 1.0

    def test_no_match_scores_zero(self) -> None:
        from dumemeval.metrics.benchmarks.beam import event_ordering_score

        score, _ = event_ordering_score("completely unrelated", ["alpha", "beta"])
        assert score == 0.0
