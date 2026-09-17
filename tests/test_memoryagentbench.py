"""测试：MemoryAgentBench 适配（四能力指标路由）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.memoryagentbench import (
    DEFAULT_CHUNK_SIZE,
    MemoryAgentBenchAdapter,
    MemoryAgentBenchData,
    chunk_text_into_sentences,
)
from dumemeval.metrics.benchmarks.memoryagentbench import (
    exact_match,
    normalize_answer,
    parse_output,
    substring_exact_match,
)
from dumemeval.models import AgentOutput

RAW = [
    {
        "context": "Normandy is in France. The capital of France is Paris.",
        "questions": ["In what country is Normandy located?", "What is the capital of France?"],
        "answers": [["France", "France"], ["Paris"]],
        "metadata": {"source": "ruler_qa1_197K"},
    },
    {
        "context": "The detective concluded the crime happened at midnight.",
        "questions": ["When did the crime happen?"],
        "answers": [["midnight"]],
        "metadata": {"source": "detective_qa"},
    },
    {
        "context": "Banking: transfer money to savings.",
        "questions": ["What should I do with my money?"],
        "answers": [["transfer money to savings"]],
        "metadata": {"source": "icl_banking77_5900shot_balance"},
    },
]


class TestMemoryAgentBenchScoring:
    def test_normalize_answer(self) -> None:
        assert normalize_answer("  The France, ") == "france"
        assert normalize_answer("a cat") == "cat"

    def test_substring_exact_match(self) -> None:
        # GT ∈ pred（方向：答案在预测里）
        assert substring_exact_match("Normandy is in France", "France") is True
        assert substring_exact_match("France", "Normandy") is False

    def test_exact_match(self) -> None:
        assert exact_match("midnight", "midnight") is True
        assert exact_match("At midnight", "midnight") is False  # 严格

    def test_parse_output(self) -> None:
        assert parse_output("Answer: 42") == "42"
        # 无 Answer: 前缀时官方第二模式取整行
        assert parse_output("The answer is 42") == "The answer is 42"
        assert parse_output("") == ""


class TestChunkTextIntoSentences:
    def test_short_text_is_one_chunk(self) -> None:
        chunks = chunk_text_into_sentences("Normandy is in France. The capital of France is Paris.")
        assert chunks
        assert "Normandy" in chunks[0]
        assert "Paris" in " ".join(chunks)

    def test_empty_returns_empty(self) -> None:
        assert chunk_text_into_sentences("") == []
        assert chunk_text_into_sentences("   ") == []

    def test_chunk_size_one_splits_sentences(self) -> None:
        """chunk_size=1 时每句单独成块（官方：单句可超过上限仍自成一块）。"""
        chunks = chunk_text_into_sentences("Hello world. Second sentence here.", chunk_size=1)
        assert len(chunks) >= 2

    def test_invalid_chunk_size_raises(self) -> None:
        with pytest.raises(ValueError, match="chunk_size"):
            chunk_text_into_sentences("x", chunk_size=0)


class TestMemoryAgentBenchAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("memoryagentbench")
        data = MemoryAgentBenchData.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 3
        t = tasks[0]
        assert t.benchmark == "memoryagentbench"
        ingest = [s for s in t.sessions if s.query is None]
        qa = [s for s in t.sessions if s.query is not None]
        assert ingest, "官方管线：context 切 chunk 后至少一段 ingest"
        assert len(qa) == 2
        assert t.sessions[-2].query == "In what country is Normandy located?"
        assert t.sessions[-1].query == "What is the capital of France?"
        assert all("请阅读并记住" in s.instruction or "部分" in s.instruction for s in ingest)
        assert "Normandy" in ingest[0].instruction
        assert all("第 " in s.instruction and "部分" in s.instruction for s in ingest)
        assert t.data["samples"][0]["n_chunks"] == len(ingest)
        assert t.data["samples"][0]["chunk_size"] == DEFAULT_CHUNK_SIZE

    def test_chunk_size_option_splits_ingest(self) -> None:
        a = MemoryAgentBenchAdapter()
        data = MemoryAgentBenchData.from_raw(RAW)
        tiny = a.build_tasks(data, chunk_size=1)
        default = a.build_tasks(data)
        tiny_ingest = [s for s in tiny[0].sessions if s.query is None]
        default_ingest = [s for s in default[0].sessions if s.query is None]
        assert len(tiny_ingest) >= len(default_ingest)

    def test_evaluate_substring_route(self) -> None:
        a = get_benchmark("memoryagentbench")
        task = a.build_tasks(MemoryAgentBenchData.from_raw(RAW))[0]
        qas = task.data["samples"][0]
        outputs = [
            AgentOutput(query=qas["questions"][0], output="Normandy is located in France"),
            AgentOutput(query=qas["questions"][1], output="Paris is the capital"),
        ]
        metrics = a.evaluate(task, outputs)
        assert metrics["accuracy"] == 1.0
        assert metrics["accuracy_ruler_qa1_197K"] == 1.0

    def test_evaluate_exact_match_route(self) -> None:
        a = get_benchmark("memoryagentbench")
        task = a.build_tasks(MemoryAgentBenchData.from_raw(RAW))[1]
        qas = task.data["samples"][0]
        outputs = [AgentOutput(query=qas["questions"][0], output="midnight")]
        metrics = a.evaluate(task, outputs)
        assert metrics["accuracy"] == 1.0
        # 严格 exact_match：加前缀会判错
        outputs2 = [AgentOutput(query=qas["questions"][0], output="The crime happened at midnight")]
        metrics2 = a.evaluate(task, outputs2)
        assert metrics2["accuracy"] == 0.0

    def test_evaluate_icl_parse_route(self) -> None:
        a = get_benchmark("memoryagentbench")
        task = a.build_tasks(MemoryAgentBenchData.from_raw(RAW))[2]
        qas = task.data["samples"][0]
        # ICL 先 parse_output：Answer: 前缀后内容参与 exact_match
        outputs = [AgentOutput(query=qas["questions"][0], output="Answer: transfer money to savings")]
        metrics = a.evaluate(task, outputs)
        assert metrics["accuracy"] == 1.0

    def test_load_real_parquet(self) -> None:
        root = Path("/Users/yueqi/Coding/Agent/Memroy/Dataset/data/MemoryAgentBench/data")
        if not root.exists():
            pytest.skip("MemoryAgentBench 数据不在本地")
        data = MemoryAgentBenchData.load_parquet_dir(root)
        assert len(data.samples) > 0
        assert all(s.questions for s in data.samples)
        sources = {s.source for s in data.samples}
        assert any("ruler" in s or "event" in s for s in sources)


class TestRecsysExcluded:
    def test_recsys_excluded_from_denominator(self) -> None:
        """recsys 不支持 → 跳过并留痕，不进分母（旧实现恒 0 拉低 accuracy）。"""
        from dumemeval.metrics import MetricInput
        from dumemeval.metrics.benchmarks.memoryagentbench import MemoryAgentBenchCalculator
        from dumemeval.models import EvalTask

        task = EvalTask(
            name="mab_test",
            data={
                "samples": [
                    {
                        "source": "event_qa",
                        "questions": ["What did Alice buy?"],
                        "answers": [["coffee"]],
                    },
                    {
                        "source": "recsys_task",
                        "questions": ["Recommend items."],
                        "answers": [["B01ABC2DEF"]],
                    },
                ]
            },
        )
        outputs = [AgentOutput(query="What did Alice buy?", output="she bought coffee")]
        bundle = MemoryAgentBenchCalculator().calculate(MetricInput(task=task, outputs=outputs))
        assert bundle.values["accuracy"] == 1.0  # recsys 不进分母，1/1 而非 1/2
        skipped = [d for d in bundle.details if d.get("skipped")]
        assert len(skipped) == 1
        assert "unsupported" in skipped[0]["reason"]
