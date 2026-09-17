"""测试：Locomo-Plus 适配（6 类 LLM judge 评分）。"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.locomo_plus import LocomoPlusAdapter, LocomoPlusData
from dumemeval.metrics.benchmarks.locomo_plus import build_judge_prompt, label_to_score, parse_judge_label
from dumemeval.models import AgentOutput
from dumemeval.verifier.base import Verdict

RAW: list[dict[str, object]] = [
    {
        "relation_type": "causal",
        "cue_dialogue": "A: After learning to say 'no', I've felt a lot less stressed overall.\nB: That's a great skill.",
        "trigger_query": "A: I ended up volunteering for that project, and now I'm totally overwhelmed.",
        "time_gap": "two weeks later",
        "model_name": "gpt-4o-mini",
        "scores": {"mpnet": 0.4},
        "ranks": {"mpnet": 262},
        "final_similarity_score": 0.509,
    }
]


class TestLocomoPlusScoring:
    def test_label_to_score(self) -> None:
        assert label_to_score("correct") == 1.0
        assert label_to_score("partial") == 0.5
        assert label_to_score("wrong") == 0.0
        assert label_to_score("") == 0.0
        assert label_to_score("unknown") == 0.0

    def test_parse_judge_label_json(self) -> None:
        assert parse_judge_label('{"label": "correct", "reason": "ok"}') == "correct"
        assert parse_judge_label('{"label": "partial"}') == "partial"
        assert parse_judge_label('{"label": "wrong"}') == "wrong"

    def test_parse_judge_label_keyword(self) -> None:
        assert parse_judge_label("The answer is correct.") == "correct"
        assert parse_judge_label("Partially right") == "partial"
        assert parse_judge_label("Wrong answer") == "wrong"
        assert parse_judge_label("") == ""

    def test_build_judge_prompt_fills_fields(self) -> None:
        prompt = build_judge_prompt("multi-hop", "evidence text", "pred text", "gold text")
        assert "evidence text" in prompt
        assert "pred text" in prompt
        assert "gold text" in prompt
        # Cognitive 类无 gold
        cognitive = build_judge_prompt("Cognitive", "evidence", "pred")
        assert "gold" not in cognitive or "{gold}" not in cognitive


class TestLocomoPlusAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("locomo_plus")
        data = LocomoPlusData.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "locomo_plus"
        assert len(t.sessions) == 2
        assert "say 'no'" in t.sessions[0].instruction
        assert t.sessions[1].query == RAW[0]["trigger_query"]

    def test_evaluate_with_judge(self) -> None:
        a = LocomoPlusAdapter(judge=lambda pred, gold, q: True)
        task = a.build_tasks(LocomoPlusData.from_raw(RAW))[0]
        outputs = [AgentOutput(query=str(RAW[0]["trigger_query"]), output="I should have said no.")]
        metrics = a.evaluate(task, outputs)
        assert metrics["score"] == 1.0
        assert metrics["score_causal"] == 1.0

    def test_evaluate_no_judge_uses_official_prompt(self) -> None:
        a = get_benchmark("locomo_plus")
        task = a.build_tasks(LocomoPlusData.from_raw(RAW))[0]
        outputs = [AgentOutput(query=str(RAW[0]["trigger_query"]), output="I should have said no.")]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify_with_prompt") as mock_verify:
            mock_verify.return_value = Verdict(label="", score=0.0, raw='{"label": "correct"}')
            metrics = a.evaluate(task, outputs)
        assert metrics["score"] == 1.0

    def test_evaluate_partial_score(self) -> None:
        a = LocomoPlusAdapter(judge=lambda pred, gold, q: False)
        task = a.build_tasks(LocomoPlusData.from_raw(RAW))[0]
        outputs = [AgentOutput(query=str(RAW[0]["trigger_query"]), output="irrelevant")]
        metrics = a.evaluate(task, outputs)
        assert metrics["score"] == 0.0

    def test_load_real_data(self) -> None:
        path = Path(
            "/Users/yueqi/Coding/Agent/Memroy/Dataset/benchmarks/conversation/Locomo-Plus/data/locomo_plus.json"
        )
        if not path.exists():
            pytest.skip("Locomo-Plus 数据不在本地")
        data = LocomoPlusData.load_json(path)
        assert len(data.samples) > 0
        assert all(s.trigger_query and s.cue_dialogue for s in data.samples)


class TestInjectedJudgePartial:
    def test_float_judge_gives_partial_credit(self) -> None:
        """注入 judge 返回 float（0~1）→ partial=0.5 档（旧实现 bool 丢 partial）。"""
        from dumemeval.metrics import MetricInput
        from dumemeval.metrics.benchmarks.locomo_plus import LocomoPlusCalculator
        from dumemeval.models import EvalTask

        task = EvalTask(
            name="lp",
            data={
                "samples": [
                    {
                        "question": "What happened?",
                        "answer": "partial answer",
                        "category": "single-hop",
                        "rubrics": [],
                    }
                ]
            },
        )
        task.data["questions"] = [task.data["samples"][0]["question"]]  # calculator 兼容字段
        outputs = [AgentOutput(query="What happened?", output="half right")]
        for raw, expected in [(0.5, 0.5), (1.0, 1.0), (0.0, 0.0), (True, 1.0), (False, 0.0)]:

            def constant_judge(_pred: str, _gold: str, _q: str, _score: float = float(raw)) -> float:
                return _score

            bundle = LocomoPlusCalculator(judge=constant_judge).calculate(
                MetricInput(task=task, outputs=outputs)
            )
            assert bundle.values["score"] == pytest.approx(expected), f"judge={raw!r}"
