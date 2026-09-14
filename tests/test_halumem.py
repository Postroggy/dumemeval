"""测试：HaluMem 适配（三阶段指标）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.halumem import HaluMemData
from dumemeval.models import AgentOutput, EvalResult

RAW = [
    {
        "uuid": "u1",
        "sessions": [
            {
                "dialogue": [
                    {"role": "user", "content": "I bought a new car."},
                    {"role": "assistant", "content": "Great choice!"},
                ],
                "memory_points": [
                    {
                        "index": 0,
                        "memory_content": "User bought a new car",
                        "memory_source": "primary",
                        "is_update": "False",
                    },
                    {
                        "index": 1,
                        "memory_content": "User bought a house",
                        "memory_source": "interference",
                        "is_update": "False",
                    },
                    {
                        "index": 2,
                        "memory_content": "User's car is red",
                        "memory_source": "primary",
                        "is_update": "True",
                    },
                ],
                "questions": [{"question": "What did the user buy?", "answer": "a new car", "evidence": []}],
            }
        ],
    }
]


class TestHaluMemAdapter:
    def test_from_raw_and_build(self) -> None:
        a = get_benchmark("halumem")
        data = HaluMemData.from_raw(RAW)
        assert len(data.users) == 1
        user = data.users[0]
        assert len(user.memory_points) == 3
        assert len(user.updates) == 1  # is_update=True
        assert len(user.qa) == 1

        tasks = a.build_tasks(data)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.benchmark == "halumem"
        assert len(t.sessions) == 2  # 1 dialogue + 1 qa
        assert "bought a new car" in t.sessions[0].instruction

    def test_evaluate_with_judge(self) -> None:
        # judge 恒真：integrity 满分、update 归 Correct、QA 归 Correct。
        # 被测记忆库文本来自 memory_files（dumemeval 被测 memory 后端映射）
        a = get_benchmark("halumem")
        from dumemeval.datasets.benchmarks.halumem import HaluMemAdapter

        a = HaluMemAdapter(judge=lambda pred, gold, q: True)
        task = a.build_tasks(HaluMemData.from_raw(RAW))[0]
        qas = task.data["qa"]
        outputs = [AgentOutput(query=qas[0]["question"], output="a new car")]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        # 评测层未传 memory_files → 空记忆库 → 官方规则 integrity 记 0
        assert metrics["integrity_recall_all"] == pytest.approx(0.0)
        assert metrics["update_correct_ratio"] == pytest.approx(1.0)
        assert metrics["qa_correct_ratio"] == pytest.approx(1.0)

    def test_calculator_with_memory_files_judge_true(self) -> None:
        """calculator 直测：memory_files 提供被测记忆库 → judge 恒真 → 满分。"""
        from dumemeval.metrics import MetricInput
        from dumemeval.metrics.benchmarks.halumem import HaluMemCalculator

        a = get_benchmark("halumem")
        task = a.build_tasks(HaluMemData.from_raw(RAW))[0]
        qas = task.data["qa"]
        outputs = [AgentOutput(query=qas[0]["question"], output="a new car")]
        bundle = HaluMemCalculator(judge=lambda pred, gold, q: True).calculate(
            MetricInput(
                result=EvalResult(task_name=task.name, memory_backend="m"),
                task=task,
                outputs=outputs,
                memory_files={"MEMORY.md": "User bought a new car"},
            )
        )
        # integrity: 2 条非 interference，judge 恒真 score=2 → recall=1.0
        assert bundle.values["integrity_recall_all"] == pytest.approx(1.0)
        # interference: judge 恒真 score=2（≠0）→ accuracy=0.0
        assert bundle.values["interference_accuracy"] == pytest.approx(0.0)

    def test_calculator_official_prompts_lazy_llm(self) -> None:
        """懒加载路径：官方 prompt + JSON score 解析（2→满分，0→未覆盖）。"""
        from unittest.mock import patch

        from dumemeval.metrics import MetricInput
        from dumemeval.metrics.benchmarks.halumem import HaluMemCalculator
        from dumemeval.verifier.base import Verdict

        a = get_benchmark("halumem")
        task = a.build_tasks(HaluMemData.from_raw(RAW))[0]
        outputs = [AgentOutput(query=task.data["qa"][0]["question"], output="a new car")]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify_with_prompt") as mock_verify:
            # integrity: 首条 score=2（覆盖）、次条（interference）score=0（未提，正确）
            mock_verify.side_effect = [
                Verdict(label="", score=0.0, reason="", raw='{"reasoning": "r", "score": "2"}'),
                Verdict(label="", score=0.0, reason="", raw='{"reasoning": "r", "score": "0"}'),
                Verdict(
                    label="", score=0.0, reason="", raw='{"reasoning": "r", "evaluation_result": "Correct"}'
                ),
                Verdict(
                    label="", score=0.0, reason="", raw='{"reasoning": "r", "evaluation_result": "Correct"}'
                ),
            ]
            bundle = HaluMemCalculator().calculate(
                MetricInput(
                    result=EvalResult(task_name=task.name, memory_backend="m"),
                    task=task,
                    outputs=outputs,
                    memory_files={"MEMORY.md": "User bought a new car"},
                )
            )
        # 官方 integrity prompt 被使用（含 memories/expected 占位）
        first_prompt = mock_verify.call_args_list[0].args[0]
        assert "Memory Integrity" in first_prompt
        assert "User bought a new car" in first_prompt
        # 2 条 golden（1 primary judge=2，1 interference judge=0）+ 1 update + 1 qa
        assert bundle.values["integrity_recall_all"] == pytest.approx(1.0)
        assert bundle.values["interference_accuracy"] == pytest.approx(1.0)
        assert bundle.values["update_correct_ratio"] == pytest.approx(1.0)
        assert bundle.values["qa_correct_ratio"] == pytest.approx(1.0)

    def test_evaluate_judge_false(self) -> None:
        from dumemeval.datasets.benchmarks.halumem import HaluMemAdapter

        a = HaluMemAdapter(judge=lambda pred, gold, q: False)
        task = a.build_tasks(HaluMemData.from_raw(RAW))[0]
        qas = task.data["qa"]
        outputs = [AgentOutput(query=qas[0]["question"], output="a red car")]
        metrics = a.evaluate(EvalResult(task_name=task.name, memory_backend="m"), task, outputs)
        assert metrics["integrity_recall_all"] == pytest.approx(0.0)
        assert metrics["interference_accuracy"] == pytest.approx(1.0)  # 反向计分
        assert metrics["qa_hallucination_ratio"] == pytest.approx(1.0)

    def test_no_data_returns_empty(self) -> None:
        a = get_benchmark("halumem")
        data = HaluMemData.from_raw([])
        assert a.build_tasks(data) == []
