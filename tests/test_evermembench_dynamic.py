"""测试：EverMemBench-Dynamic 适配（MC 规则 + OE judge）。"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.evermembench_dynamic import (
    EverMemBenchDynamicAdapter,
    EverMemBenchDynamicData,
)
from dumemeval.metrics.benchmarks.evermembench_dynamic import evaluate_mc, parse_mc_answer
from dumemeval.models import AgentOutput, EvalResult
from dumemeval.verifier.base import Verdict

RAW = [
    {
        "topic_id": "01",
        "dialogues": "[2025-10-20][Group 3][Alice] SQL 优化完成\n[2025-10-21][Group 3][Bob] 峰值 CPU 65%",
        "qa": [
            {
                "id": "F_SH_Top01_001",
                "question": "峰值 CPU 是多少？",
                "answer": "D",
                "options": {"A": "45%", "B": "55%", "C": "60%", "D": "65%"},
            },
            {
                "id": "MA_U_Top01_002",
                "question": "What was the peak CPU usage?",
                "answer": "65%",
                "options": None,
            },
        ],
    }
]


class TestEverMemParseMc:
    def test_parse_direct_letter(self) -> None:
        assert parse_mc_answer("D") == "D"
        assert parse_mc_answer("A") == "A"

    def test_parse_delimited(self) -> None:
        assert parse_mc_answer("The answer is D.") == "D"
        assert parse_mc_answer("B) Option") == "B"
        assert parse_mc_answer("I choose C: correct") == "C"

    def test_parse_answer_is(self) -> None:
        assert parse_mc_answer("answer is A") == "A"
        assert parse_mc_answer("the choice is B") == "B"

    def test_parse_unparseable(self) -> None:
        assert parse_mc_answer("not sure") == "NOT SURE"  # 返回原串 → 判错
        assert parse_mc_answer("") == ""

    def test_evaluate_mc(self) -> None:
        assert evaluate_mc("D", "D") is True
        assert evaluate_mc("The answer is D.", "D") is True
        assert evaluate_mc("A", "D") is False
        assert evaluate_mc("[failed]", "D") is False  # 失败标记
        assert evaluate_mc("D", "D. 65%") is True  # golden 带选项文本


class TestEverMemBenchAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("evermembench_dynamic")
        data = EverMemBenchDynamicData.from_raw(RAW)
        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "evermembench_dynamic"
        assert len(t.sessions) == 3  # 1 对话注入 + 2 题
        assert "SQL 优化" in t.sessions[0].instruction
        assert "只输出选项字母" in t.sessions[1].instruction

    def test_evaluate_mc_rules(self) -> None:
        a = EverMemBenchDynamicAdapter(judge=lambda pred, gold, q: True)
        task = a.build_tasks(EverMemBenchDynamicData.from_raw(RAW))[0]
        qas = task.data["questions"]
        outputs = [
            AgentOutput(query=qas[0]["question"], output="D"),
            AgentOutput(query=qas[1]["question"], output="65%"),
        ]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert metrics["accuracy"] == 1.0
        assert metrics["accuracy_multiple_choice"] == 1.0
        assert metrics["accuracy_open_ended"] == 1.0
        assert metrics.by_category["F"]["count"] == 1.0
        assert metrics.by_category["MA"]["count"] == 1.0

    def test_evaluate_mc_wrong(self) -> None:
        a = EverMemBenchDynamicAdapter(judge=lambda pred, gold, q: True)
        task = a.build_tasks(EverMemBenchDynamicData.from_raw(RAW))[0]
        qas = task.data["questions"]
        outputs = [
            AgentOutput(query=qas[0]["question"], output="A"),
            AgentOutput(query=qas[1]["question"], output="65%"),
        ]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert metrics["accuracy_multiple_choice"] == 0.0

    def test_oe_no_judge_falls_back_to_llm(self) -> None:
        """懒加载路径走官方 llm_judge 模板（宽容式 CORRECT/WRONG JSON）。"""
        a = get_benchmark("evermembench_dynamic")
        task = a.build_tasks(EverMemBenchDynamicData.from_raw(RAW))[0]
        qas = task.data["questions"]
        outputs = [
            AgentOutput(query=qas[0]["question"], output="D"),
            AgentOutput(query=qas[1]["question"], output="65%"),
        ]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify_with_prompt") as mock_verify:
            mock_verify.return_value = Verdict(label="", score=0.0, reason="ok", raw='{"label": "CORRECT"}')
            metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert metrics["accuracy_open_ended"] == 1.0
        # 官方 prompt 被使用（含 ±1 天宽容条款与占位填充）
        used_prompt = mock_verify.call_args.args[0]
        assert "+/- 1 day" in used_prompt and "65%" in used_prompt

    def test_load_real_dir(self) -> None:
        root = Path("/Users/yueqi/Coding/Agent/Memroy/Dataset/data/EverMemBench-Dynamic")
        if not (root / "01").exists():
            pytest.skip("EverMemBench-Dynamic 数据不在本地")
        data = EverMemBenchDynamicData.load_dir(root)
        assert len(data.topics) >= 1
        assert all(t.qa for t in data.topics)
        assert any(q.options is None for t in data.topics for q in t.qa)  # 有 OE 题
