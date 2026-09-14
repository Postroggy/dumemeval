"""测试：MemoryCD 适配（跨域个性化，确定性指标）。"""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.memorycd import MemoryCDData
from dumemeval.evaluation import CalculatorBenchmarkScorer
from dumemeval.metrics.benchmarks.memorycd import mae, ndcg_at_k, parse_rating, recall_at_k, rouge_l_f1
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput, SampleResult

RAW = [
    {
        "user_id": "u1",
        "interactions": {
            "Beauty_and_Personal_Care": [
                {"asin": "B1", "title": "Cream", "rating": 4.0, "text": "Good cream"},
                {"asin": "B2", "title": "Lotion", "rating": 5.0, "text": "Great lotion"},
            ],
            "Books": [
                {"asin": "B3", "title": "Novel", "rating": 3.0, "text": "Ok book"},
                {"asin": "B4", "title": "Cookbook", "rating": 2.0, "text": "Boring"},
            ],
        },
    }
]


class TestMemoryCDScoring:
    def test_parse_rating(self) -> None:
        assert parse_rating("4") == 4.0
        assert parse_rating("4.5") == 4.5
        assert parse_rating("I think it deserves 3 stars") == 3.0
        assert parse_rating("") is None

    def test_mae(self) -> None:
        assert mae(4.0, 3.0) == 1.0
        assert mae(3.0, 3.0) == 0.0

    def test_rouge_l(self) -> None:
        assert rouge_l_f1("the cat sat on the mat", "the cat sat on the mat") == 1.0
        assert rouge_l_f1("the cat", "the cat sat on the mat") > 0
        assert rouge_l_f1("totally different", "the cat") == 0.0

    def test_ndcg_recall(self) -> None:
        assert ndcg_at_k(["B1", "B2", "B3"], "B1", 5) == 1.0
        assert ndcg_at_k(["B1", "B2"], "B3", 5) == 0.0
        # 官方折扣分级：rank2=1/log2(3)，rank3=0.5（非 0/1 化）
        assert ndcg_at_k(["B1", "B2", "B3"], "B2", 5) == pytest.approx(1 / math.log2(3))
        assert ndcg_at_k(["B1", "B2", "B3"], "B3", 5) == pytest.approx(0.5)
        assert recall_at_k(["B1", "B3"], "B3", 5) == 1.0
        assert recall_at_k(["B1", "B2"], "B3", 5) == 0.0


class TestMemoryCDAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("memorycd")
        data = MemoryCDData.from_raw(RAW)
        assert len(data.users) == 1
        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "memorycd"
        # 1 记忆 session + 2 目标域交互（Beauty 域 2 条）
        assert len(t.sessions) == 3
        assert "Books" in t.sessions[0].instruction

    def test_evaluate_rating_mae(self) -> None:
        a = get_benchmark("memorycd")
        task = a.build_tasks(MemoryCDData.from_raw(RAW))[0]
        tasks_list = task.data["tasks"]
        outputs = [
            AgentOutput(query=tasks_list[0]["query"], output="5"),
            AgentOutput(query=tasks_list[1]["query"], output="3"),
        ]
        result = CalculatorBenchmarkScorer("memorycd").score(
            MetricInput(
                task=task,
                outputs=outputs,
                samples=[
                    SampleResult(sample_id=str(i), query=o.query, response=o.output)
                    for i, o in enumerate(outputs)
                ],
            )
        )
        # target: 4.0, 5.0 → pred 5, 3 → MAE=(1+2)/2=1.5
        assert result.values["mae"] == pytest.approx(1.5)
        # RMSE = sqrt((1+4)/2) = sqrt(2.5)
        assert result.values["rmse"] == pytest.approx((2.5) ** 0.5)

    def test_load_real_data(self) -> None:
        path = Path(
            "/Users/yueqi/Coding/Agent/Memroy/Dataset/data/MemoryCD/users/cross_domain_users_sampled.jsonl.gz"
        )
        if not path.exists():
            pytest.skip("MemoryCD 数据不在本地")
        data = MemoryCDData.load_gz(path, limit=5)
        assert len(data.users) == 5
        assert all(
            set(u.interactions.keys())
            == {"Beauty_and_Personal_Care", "Books", "Electronics", "Home_and_Kitchen"}
            for u in data.users
        )
