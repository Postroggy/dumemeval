"""测试：memsim / MemDaily 适配（确定性 accuracy + recall@step）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.metrics.benchmarks.memsim import memsim_accuracy, parse_step_ids, recall_at_step_ids
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput, SampleResult

RAW = {
    "simple": {
        "roles": [
            {
                "tid": "0",
                "message_list": [
                    {
                        "mid": "0",
                        "message": "我的上司就只有高中学历。",
                        "time": "2024年04月01日",
                        "place": "广东深圳",
                    }
                ],
                "QA": {
                    "qid": "0",
                    "question": "那我的上司是哪个学校毕业的呢？",
                    "answer": "高中",
                    "target_step_id": "[0]",
                    "choices": "{'A': '本科', 'B': '专科', 'C': '硕士', 'D': '高中'}",
                    "ground_truth": "D",
                },
            }
        ]
    }
}


class TestMemSimScoring:
    def test_parse_step_ids(self) -> None:
        assert parse_step_ids("[0]") == [0]
        assert parse_step_ids("[0, 4]") == [0, 4]
        assert parse_step_ids([1, 2]) == [1, 2]

    def test_recall(self) -> None:
        assert recall_at_step_ids("[0, 4]", "[0, 4]") == 1.0
        assert recall_at_step_ids("[0]", "[0, 4]") == 0.5
        assert recall_at_step_ids("[]", "[0, 4]") == 0.0

    def test_accuracy_exact_match(self) -> None:
        assert memsim_accuracy("D", "D") == 1.0
        assert memsim_accuracy("d", "D") == 0.0  # 官方无大小写容错
        assert memsim_accuracy("", "D") == 0.0


class TestMemSimAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("memsim")
        data = a.data_type.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "memsim"
        assert len(t.sessions) == 2
        assert "高中学历" in t.sessions[0].instruction
        assert "那我的上司是哪个学校毕业的呢？" in t.sessions[1].instruction

    def test_evaluate(self) -> None:
        a = get_benchmark("memsim")
        task = a.build_tasks(a.data_type.from_raw(RAW))[0]
        q = task.data["qa"][0]["question"]
        outputs = [AgentOutput(query=q, output="D")]
        result = CalculatorBenchmarkScorer("memsim").score(
            MetricInput(
                task=task, samples=[SampleResult(sample_id="0", query=q, response="D")], outputs=outputs
            )
        )
        assert result.values["accuracy"] == 1.0
        assert result.values["accuracy_simple"] == 1.0

    def test_evaluate_wrong_answer(self) -> None:
        a = get_benchmark("memsim")
        task = a.build_tasks(a.data_type.from_raw(RAW))[0]
        q = task.data["qa"][0]["question"]
        outputs = [AgentOutput(query=q, output="A")]
        result = CalculatorBenchmarkScorer("memsim").score(
            MetricInput(
                task=task, samples=[SampleResult(sample_id="0", query=q, response="A")], outputs=outputs
            )
        )
        assert result.values["accuracy"] == 0.0

    def test_load_real_data(self) -> None:
        path = Path(
            "/Users/yueqi/Coding/Agent/Memroy/Dataset/benchmarks/conversation/memsim/data_generation/final_dataset/memdaily.json"
        )
        if not path.exists():
            pytest.skip("memsim 数据不在本地")
        from dumemeval.datasets.benchmarks.memsim import MemSimData

        data = MemSimData.load_json(path)
        assert len(data.trajectories) > 0
        assert all(t.qa is not None for t in data.trajectories)
