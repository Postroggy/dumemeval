"""测试：PerLTQA 适配（EM + token F1，适配层判分）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.perltqa import PerLTQAData
from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.metrics.benchmarks.perltqa import exact_match, token_f1
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput, SampleResult

RAW = [
    {
        "Zhang Xiaohong": {
            "profile": [
                {
                    "Question": "What is the gender?",
                    "Answer": "Zhang Xiaohong is female.",
                    "Reference Memory": "Gender",
                    "Memory Anchors": [{"female": [-1, -1]}],
                },
                {
                    "Question": "What is the age?",
                    "Answer": "Zhang Xiaohong is 30 years old.",
                    "Reference Memory": "Age",
                    "Memory Anchors": [{"30": [-1, -1]}],
                },
            ],
            "events": [
                {
                    "1_0_0": [
                        {
                            "Question": "What happened at the event?",
                            "Answer": "She went to the park.",
                            "Reference Memory": ["1_0_0"],
                            "Memory Anchors": [{"park": [0, 4]}],
                        },
                    ]
                }
            ],
        }
    }
]


class TestPerLTQAScoring:
    def test_token_f1(self) -> None:
        assert token_f1("Zhang Xiaohong is female", "Zhang Xiaohong is female") == 1.0
        assert token_f1("She is female", "Zhang Xiaohong is female") > 0
        assert token_f1("unrelated", "Zhang Xiaohong is female") == 0.0

    def test_exact_match(self) -> None:
        assert exact_match("female", "Female") is True
        assert exact_match("female", "male") is False


class TestPerLTQAAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("perltqa")
        data = PerLTQAData.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "perltqa"
        # profile 2 题 + events 1 题 = 3 题 + 1 注入 session
        assert len(t.sessions) == 4
        assert t.sessions[1].query == "What is the gender?"

    def test_evaluate(self) -> None:
        a = get_benchmark("perltqa")
        task = a.build_tasks(PerLTQAData.from_raw(RAW))[0]
        qas = task.data["questions"]
        outputs = [
            AgentOutput(query=qas[0]["question"], output="Zhang Xiaohong is female"),
            AgentOutput(query=qas[1]["question"], output="30 years old"),
            AgentOutput(query=qas[2]["question"], output="park"),
        ]
        result = CalculatorBenchmarkScorer("perltqa").score(
            MetricInput(
                task=task,
                outputs=outputs,
                samples=[
                    SampleResult(sample_id=str(i), query=o.query, response=o.output)
                    for i, o in enumerate(outputs)
                ],
            )
        )
        assert result.values["f1"] > 0
        assert result.values["f1_profile"] > 0
        assert result.values["f1_events"] > 0

    def test_load_real_data(self) -> None:
        path = Path(
            "/Users/yueqi/Coding/Agent/Memroy/Dataset/benchmarks/conversation/PerLTQA/Dataset/en_v2/perltqa_en_v2.json"
        )
        if not path.exists():
            pytest.skip("PerLTQA 数据不在本地")
        data = PerLTQAData.load_json(path)
        assert len(data.items) > 0
        assert all(i.question and i.answer for i in data.items)
        sections = {i.section for i in data.items}
        assert sections == {"profile", "social_relationship", "events", "dialogues"}
