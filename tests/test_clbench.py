"""测试：CL-bench 适配（Solving Rate = LLM judge 全有或全无）。"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.clbench import CLBenchAdapter, CLBenchData
from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.metrics.benchmarks.clbench import build_grading_prompt, parse_overall_score
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput, SampleResult
from dumemeval.verifier.base import Verdict

RAW = [
    {
        "id": "1",
        "messages": [
            {"role": "system", "content": "你是规则引擎。"},
            {"role": "user", "content": "Twisted Cryptids 规则：Sighting card 是 X。"},
            {"role": "user", "content": "什么是 Sighting card？"},
        ],
        "rubrics": [
            "The response should define what a Sighting card is.",
            "The response should mention its role.",
        ],
        "metadata": {
            "task_id": "t1",
            "context_category": "Rule System Application",
            "sub_category": "Game Mechanics",
        },
    }
]


class TestCLBenchScoring:
    def test_parse_overall_score(self) -> None:
        assert parse_overall_score('{"Overall Score": 1}') == 1
        assert parse_overall_score('{"Overall Score": 0}') == 0
        assert parse_overall_score("Overall Score: 1") == 1
        assert parse_overall_score("garbage") is None
        assert parse_overall_score("") is None

    def test_build_grading_prompt(self) -> None:
        prompt = build_grading_prompt(["rubric 1", "rubric 2"], "student answer")
        assert "rubric 1" in prompt
        assert "rubric 2" in prompt
        assert "student answer" in prompt
        assert "all-or-nothing" in prompt


class TestCLBenchAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("clbench")
        data = CLBenchData.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "clbench"
        assert len(t.sessions) == 2
        assert "Twisted Cryptids" in t.sessions[0].instruction
        assert t.sessions[1].query == "什么是 Sighting card？"

    def test_evaluate_with_judge(self) -> None:
        a = CLBenchAdapter(judge=lambda pred, gold, q: True)
        task = a.build_tasks(CLBenchData.from_raw(RAW))[0]
        outputs = [AgentOutput(query="什么是 Sighting card？", output="Sighting card 是 X，用于 Y。")]
        metrics = CalculatorBenchmarkScorer("clbench", judge=lambda pred, gold, q: True).score(
            MetricInput(
                task=task,
                outputs=outputs,
                samples=[SampleResult(sample_id="0", query=outputs[0].query, response=outputs[0].output)],
            )
        )
        assert metrics.values["solving_rate"] == 1.0
        assert metrics.values["solving_rate_Rule System Application"] == 1.0

    def test_evaluate_no_judge_official_prompt(self) -> None:
        a = get_benchmark("clbench")
        task = a.build_tasks(CLBenchData.from_raw(RAW))[0]
        outputs = [AgentOutput(query="什么是 Sighting card？", output="Sighting card 是 X。")]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify_with_prompt") as mock_verify:
            mock_verify.return_value = Verdict(label="", score=0.0, raw='{"Overall Score": 0}')
            metrics = CalculatorBenchmarkScorer("clbench", judge=lambda pred, gold, q: False).score(
                MetricInput(
                    task=task,
                    outputs=outputs,
                    samples=[SampleResult(sample_id="0", query=outputs[0].query, response=outputs[0].output)],
                )
            )
        assert metrics.values["solving_rate"] == 0.0

    def test_load_real_data(self) -> None:
        path = Path("/Users/yueqi/Coding/Agent/Memroy/Dataset/data/CL-bench/CL-bench.jsonl")
        if not path.exists():
            pytest.skip("CL-bench 数据不在本地")
        data = CLBenchData.load_jsonl(path)
        assert len(data.samples) > 0
        assert all(s.rubrics for s in data.samples)
        assert all(s.question for s in data.samples)
