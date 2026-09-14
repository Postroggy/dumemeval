"""测试：MemoryBench 适配（28 子集指标路由）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.memorybench import MemoryBenchData
from dumemeval.metrics.benchmarks.memorybench import exact_match, rouge_l_f1, token_f1
from dumemeval.models import AgentOutput, EvalResult


def _sample(dataset: str, question: str, golden: str, category: int = 0) -> dict[str, object]:
    return {
        "test_idx": 0,
        "origin_question": question,
        "info": {"golden_answer": golden, "category": category},
        "input_prompt": "Context: conversation.",
        "dataset_name": dataset,
    }


class TestMemoryBenchScoring:
    def test_token_f1(self) -> None:
        assert token_f1("Brave by Sara Bareilles", "Brave by Sara Bareilles") == 1.0
        assert token_f1("unrelated", "Brave") == 0.0

    def test_exact_match(self) -> None:
        assert exact_match("yes", "YES") is True
        assert exact_match(" yes ", "yes") is True
        assert exact_match("nope", "yes") is False

    def test_rouge_l(self) -> None:
        assert rouge_l_f1("a b c d", "a b c d") == 1.0
        assert rouge_l_f1("a b", "a b c d") > 0


class TestMemoryBenchAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("memorybench")
        raw = [_sample("Locomo-0", "Q1?", "Brave by Sara Bareilles", 4)]
        data = MemoryBenchData.from_raw(raw)
        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "memorybench"
        assert t.name == "memorybench_Locomo-0"
        assert len(t.sessions) == 2

    def test_evaluate_locomo_f1(self) -> None:
        a = get_benchmark("memorybench")
        raw = [
            _sample("Locomo-0", "Q1?", "Brave by Sara Bareilles", 4),
            _sample("Locomo-0", "Q2?", "no info", 5),
        ]
        task = a.build_tasks(MemoryBenchData.from_raw(raw))[0]
        qas = task.data["samples"]
        outputs = [
            AgentOutput(query=qas[0]["question"], output="Brave by Sara Bareilles"),
            AgentOutput(query=qas[1]["question"], output="no information available"),
        ]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        # Q1 F1=1, Q2 cat5 拒答=1 → 全对
        assert metrics["score"] == 1.0
        assert metrics["score_Locomo-0"] == 1.0

    def test_evaluate_dialsim_fallback_judge(self) -> None:
        from dumemeval.datasets.benchmarks.memorybench import MemoryBenchAdapter

        a = MemoryBenchAdapter(judge=lambda pred, gold, q: True)
        raw = [_sample("DialSim-friends", "Q?", "the answer")]
        task = a.build_tasks(MemoryBenchData.from_raw(raw))[0]
        qas = task.data["samples"]
        # 输出与 golden 不 exact，走 LLM judge fallback
        outputs = [AgentOutput(query=qas[0]["question"], output="different wording")]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert metrics["score"] == 1.0

    def test_evaluate_lexeval_rouge(self) -> None:
        a = get_benchmark("memorybench")
        raw = [_sample("LexEval-Judge", "Q?", "the judge ruled in favor")]
        task = a.build_tasks(MemoryBenchData.from_raw(raw))[0]
        qas = task.data["samples"]
        outputs = [AgentOutput(query=qas[0]["question"], output="the judge ruled in favor")]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert metrics["score"] == 1.0

    def test_load_real_subset(self) -> None:
        root = Path("/Users/yueqi/Coding/Agent/Memroy/Dataset/data/MemoryBench/dataset")
        if not (root / "Locomo-0").exists():
            pytest.skip("MemoryBench 数据不在本地")
        data = MemoryBenchData.load_dataset_dir(root, "Locomo-0")
        assert len(data.samples) > 0
        assert all(s.question and s.dataset for s in data.samples)


class TestMeteorAndCjkRouge:
    def test_meteor_full_match_near_one(self) -> None:
        from dumemeval.metrics.benchmarks.memorybench import meteor_score

        assert meteor_score("the cat sat on the mat", "the cat sat on the mat") == pytest.approx(
            1 - 0.5 * (1 / 6) ** 3
        )

    def test_meteor_disorder_penalized(self) -> None:
        from dumemeval.metrics.benchmarks.memorybench import meteor_score

        # 词全对但顺序散乱：chunk penalty 压分（Fmean=1, chunks=6 → 0.5×1=0.5 档）
        assert meteor_score("mat the on sat cat the", "the cat sat on the mat") < 0.6
        assert meteor_score("mat the on sat cat the", "the cat sat on the mat") > 0.4

    def test_meteor_no_match_zero(self) -> None:
        from dumemeval.metrics.benchmarks.memorybench import meteor_score

        assert meteor_score("apple banana", "dog cat") == 0.0

    def test_rouge_l_cjk_char_level(self) -> None:
        """中文按字符切（旧空白 split 整句 1 token，ROUGE-L 恒 0/1 失真）。"""
        from dumemeval.metrics.benchmarks.memorybench import rouge_l_f1

        score = rouge_l_f1("我喜欢喝咖啡", "我喜欢喝茶")
        assert score > 0.7  # LCS=4（我喜欢喝）→ F1≈0.73
        assert rouge_l_f1("完全不同", "毫无关系") == 0.0
