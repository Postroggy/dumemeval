"""测试：agent multi-turn 数据集适配（官方指标，禁止跨数据集 mapping）。"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.datasets import get_benchmark
from dumemeval.datasets.benchmarks.memoryarena_reasoning import MemoryArenaMathAdapter, MemoryArenaPhysAdapter
from dumemeval.datasets.benchmarks.memoryarena_search import MemoryArenaSearchAdapter
from dumemeval.metrics import get_benchmark_calculator, outputs_from_result
from dumemeval.metrics.benchmarks.streammembench import token_overlap_score
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput, EvalResult, EvalTask
from dumemeval.verifier.base import Verdict
from dumemeval.verifier.parsers import parse_judge_response


def _result(name: str = "t") -> EvalResult:
    return EvalResult(task_name=name, memory_backend="m")


SHOPPING_RAW = [
    {
        "id": 0,
        "category": "baking_item_0",
        "questions": ["Buy almond flour B00TUDFEW2", "Buy muffin pan B08957C9ZH"],
        "answers": [
            {"target_asin": "B00TUDFEW2", "attributes": ["Almond Flour"]},
            {"target_asin": "B08957C9ZH", "attributes": ["Muffin Pan"]},
        ],
    }
]

SEARCH_RAW = [
    {
        "id": 0,
        "questions": ["Who started via an audition?", "Where did they work next?"],
        "answers": ["Sonia Uche started via an audition.", "She later worked in Lagos."],
    }
]

MATH_RAW = [
    {
        "id": 0,
        "paper_name": "toy",
        "questions": [r"Find $\nu(p)$.", r"Compute $(c_2,c_3)$."],
        "answers": [r"$\nu(p)=\overline{ev}_p$", r"$(c_2,c_3)=(-1,-1)$"],
        "backgrounds": ["LaTeX: \\nu is a function.", "Fact: locality equations."],
    }
]

STREAM_RAW = {
    "language": "zh",
    "items": [
        {
            "participant": "A1_JAKE",
            "day": "DAY1",
            "segment_id": 1,
            "stream_segment": {
                "text": "Jake 的工作间有6台电脑，每台对应团队成员的眼镜，用于每3小时自动导入数据到外接硬盘。"
            },
            "evidence_anchors": [
                {
                    "evidence_id": "jake_workstation_setup",
                    "evidence_statement": (
                        "Jake 的工作间有6台电脑，每台对应团队成员的眼镜，用于每3小时自动导入数据到外接硬盘。"
                    ),
                    "tasks": {
                        "initial_task": {
                            "user_request": "下午录完素材后需要提醒他们做什么？",
                            "expected_behavior": "提醒应确保眼镜连接到对应电脑，并检查硬盘连接，不要建议手动拷贝。",
                        },
                        "followup_task": {
                            "user_request": "Shure 的眼镜数据没存上，该先检查哪里？",
                            "expected_behavior": "应先检查 Shure 眼镜对应的那台电脑和外接硬盘电源数据线。",
                        },
                    },
                }
            ],
        }
    ],
}

PASSING_STREAM_ANSWER = (
    "Jake 的工作间有6台电脑，每台对应团队成员的眼镜，用于每3小时自动导入数据到外接硬盘。"
    "提醒应确保眼镜连接到对应电脑，并检查硬盘连接，不要建议手动拷贝。"
)
PASSING_FOLLOWUP = (
    "Jake 的工作间有6台电脑，每台对应团队成员的眼镜，用于每3小时自动导入数据到外接硬盘。"
    "应先检查 Shure 眼镜对应的那台电脑和外接硬盘电源数据线。"
)


class TestMemoryArenaShopping:
    def test_build_uses_question_text(self) -> None:
        a = get_benchmark("memoryarena_shopping")
        task = a.build_tasks(a.data_type.from_raw(SHOPPING_RAW))[0]
        assert task.benchmark == "memoryarena_shopping"
        assert len(task.sessions) == 2
        assert "Buy almond flour B00TUDFEW2" in task.sessions[0].instruction
        assert "search[" in task.sessions[0].instruction
        assert task.task_environment.get("type") == "webshop"
        assert a.metrics() == ["match_ground_truth", "overall_success", "attribute_match"]

    def test_subset_and_max_questions(self) -> None:
        from dumemeval.datasets.benchmarks.memoryarena_shopping import MemoryArenaShoppingAdapter

        raw = [
            *SHOPPING_RAW,
            {
                "id": 1,
                "category": "other",
                "questions": ["q1", "q2", "q3"],
                "answers": [{"target_asin": "A"}, {"target_asin": "B"}, {"target_asin": "C"}],
            },
        ]
        # 扩展参数（subset/max_questions）由具体子类声明，基类类型上不可调
        a = MemoryArenaShoppingAdapter()
        tasks = a.build_tasks(a.data_type.from_raw(raw), subset=1, max_questions=1)
        assert len(tasks) == 1
        assert len(tasks[0].sessions) == 1
        assert tasks[0].data["questions"] == ["Buy almond flour B00TUDFEW2"]

    def test_exact_asin_all_steps(self) -> None:
        a = get_benchmark("memoryarena_shopping")
        task = a.build_tasks(a.data_type.from_raw(SHOPPING_RAW))[0]
        outputs = [
            AgentOutput(query="Buy almond flour B00TUDFEW2", output="Purchased B00TUDFEW2 Almond Flour"),
            AgentOutput(query="Buy muffin pan B08957C9ZH", output="Purchased B08957C9ZH Muffin Pan"),
        ]
        metrics = a.evaluate(_result(task.name), task, outputs)
        assert metrics["match_ground_truth"] == 1.0
        assert metrics["overall_success"] == 1.0
        assert metrics["attribute_match"] == 1.0
        assert "round_success" not in metrics.values
        assert "f1" not in metrics.values

    def test_partial_step_not_overall_success(self) -> None:
        a = get_benchmark("memoryarena_shopping")
        task = a.build_tasks(a.data_type.from_raw(SHOPPING_RAW))[0]
        outputs = [
            AgentOutput(query="Buy almond flour B00TUDFEW2", output="B00TUDFEW2 Almond Flour"),
            AgentOutput(query="Buy muffin pan B08957C9ZH", output="bought something else"),
        ]
        metrics = a.evaluate(_result(task.name), task, outputs)
        assert metrics["match_ground_truth"] == pytest.approx(0.5)
        assert metrics["overall_success"] == 0.0


class TestMemoryArenaSearch:
    def test_no_judge_falls_back_to_llm_judge(self) -> None:
        """无显式 judge 注入时应懒加载 LLMJudgeVerifier（search_grader prompt）
        做真实判分，而不是静默判错——这是此前的 bug：没配 judge 和 judge 判 no
        被混为一谈，导致真实评测下 accuracy 恒为 0。"""
        a = get_benchmark("memoryarena_search")
        task = a.build_tasks(a.data_type.from_raw(SEARCH_RAW))[0]
        gold = "Sonia Uche started via an audition."
        outputs = [
            AgentOutput(query="Who started via an audition?", output=gold),
            AgentOutput(query="Where did they work next?", output="She later worked in Lagos."),
        ]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify") as mock_verify:
            mock_verify.return_value = Verdict(label="yes", score=1.0, reason="matches")
            metrics = a.evaluate(_result(task.name), task, outputs)
        assert mock_verify.call_count == 2
        assert metrics["accuracy"] == 1.0
        assert "f1" not in metrics.values
        assert "match_ground_truth" not in metrics.values
        assert "round_success" not in metrics.values

    def test_empty_prediction_counts_incorrect_without_calling_llm(self) -> None:
        """空预测（agent 没输出）不该浪费一次 LLM 调用，直接判错。"""
        a = get_benchmark("memoryarena_search")
        task = a.build_tasks(a.data_type.from_raw(SEARCH_RAW))[0]
        outputs: list[AgentOutput] = []
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify") as mock_verify:
            metrics = a.evaluate(_result(task.name), task, outputs)
        assert mock_verify.call_count == 0
        assert metrics["accuracy"] == 0.0

    def test_injected_grader(self) -> None:
        a = MemoryArenaSearchAdapter(judge=lambda pred, gold, _q: gold[:12].lower() in pred.lower())
        task = a.build_tasks(a.data_type.from_raw(SEARCH_RAW))[0]
        outputs = [
            AgentOutput(query="Who started via an audition?", output="Sonia Uche started via an audition."),
            AgentOutput(query="Where did they work next?", output="unrelated"),
        ]
        metrics = a.evaluate(_result(task.name), task, outputs)
        assert metrics["accuracy"] == pytest.approx(0.5)

    def test_parse_judge_response(self) -> None:
        parsed = parse_judge_response("extracted_final_answer: Sonia\ncorrect: yes\nconfidence: 80")
        assert parsed["correct"] is True
        assert parsed["confidence"] == 80.0


class TestMemoryArenaReasoning:
    def test_math_includes_background_not_gold(self) -> None:
        a = get_benchmark("memoryarena_math")
        task = a.build_tasks(a.data_type.from_raw(MATH_RAW))[0]
        assert "LaTeX:" in task.sessions[0].instruction
        assert r"Find $\nu(p)$." in task.sessions[0].instruction
        assert r"$\nu(p)=\overline{ev}_p$" not in task.sessions[0].instruction
        assert a.metrics() == ["is_correct"]

    def test_no_judge_falls_back_to_llm_judge(self) -> None:
        """无显式 judge 注入时应懒加载 LLMJudgeVerifier（math_equivalence prompt），
        不是静默 return False（此前的 bug：真实评测下 is_correct 恒为 0）。"""
        a = get_benchmark("memoryarena_math")
        task = a.build_tasks(a.data_type.from_raw(MATH_RAW))[0]
        gold = r"$\nu(p)=\overline{ev}_p$"
        outputs = [
            AgentOutput(query=r"Find $\nu(p)$.", output=gold),
            AgentOutput(query=r"Compute $(c_2,c_3)$.", output=r"$(c_2,c_3)=(-1,-1)$"),
        ]
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify") as mock_verify:
            mock_verify.return_value = Verdict(label="yes", score=1.0, reason="equivalent")
            metrics = a.evaluate(_result(task.name), task, outputs)
        assert mock_verify.call_count == 2
        assert metrics["is_correct"] == 1.0
        assert "round_success" not in metrics.values
        assert "accuracy" not in metrics.values

    def test_math_and_phys_share_is_correct_only(self) -> None:
        math_a = MemoryArenaMathAdapter(judge=lambda pred, gold, _q: pred == gold)
        phys_a = MemoryArenaPhysAdapter(judge=lambda pred, gold, _q: pred == gold)
        math_task = math_a.build_tasks(math_a.data_type.from_raw(MATH_RAW))[0]
        phys_task = phys_a.build_tasks(phys_a.data_type.from_raw(MATH_RAW))[0]
        outputs = [
            AgentOutput(query=r"Find $\nu(p)$.", output=r"$\nu(p)=\overline{ev}_p$"),
            AgentOutput(query=r"Compute $(c_2,c_3)$.", output="wrong"),
        ]
        assert math_a.evaluate(_result(), math_task, outputs)["is_correct"] == pytest.approx(0.5)
        assert phys_a.evaluate(_result(), phys_task, outputs)["is_correct"] == pytest.approx(0.5)
        assert math_a.name == "memoryarena_math"
        assert phys_a.name == "memoryarena_phys"


class TestStreamMemBench:
    def test_labels_not_leaked_into_sessions(self) -> None:
        a = get_benchmark("streammembench")
        task = a.build_tasks(a.data_type.from_raw(STREAM_RAW))[0]
        joined = "\n".join(s.instruction for s in task.sessions)
        assert "expected_behavior" not in joined
        assert "evidence_statement" not in joined
        assert "下午录完素材后需要提醒他们做什么？" in task.sessions[1].instruction
        data = task.data
        assert isinstance(data, dict)
        assert "Jake 的工作间有6台电脑" in str(data.get("evidence_statement"))

    def test_official_four_metrics(self) -> None:
        a = get_benchmark("streammembench")
        task = a.build_tasks(a.data_type.from_raw(STREAM_RAW))[0]
        data = task.data if isinstance(task.data, dict) else {}
        initial = str(data["initial_user_request"])
        followup = str(data["followup_user_request"])
        evidence = str(data["evidence_statement"])
        outputs = [
            AgentOutput(query=initial, output=PASSING_STREAM_ANSWER),
            AgentOutput(query=followup, output=PASSING_FOLLOWUP),
        ]
        metrics = a.evaluate(_result(task.name), task, outputs)
        assert set(a.metrics()) == {
            "fidelity",
            "initial_evidence_use",
            "feedback_incorporation",
            "followup_reuse",
        }
        assert metrics["fidelity"] == 0.0
        assert metrics["initial_evidence_use"] == 1.0
        assert metrics["feedback_incorporation"] == 0.0
        assert metrics["feedback_incorporation_applicable"] == 0.0
        assert metrics["followup_reuse"] == 1.0
        assert "accuracy" not in metrics.values
        assert "f1" not in metrics.values
        calc = get_benchmark_calculator("streammembench")
        with_mem = calc.calculate(
            MetricInput(
                result=_result(task.name),
                task=task,
                outputs=outputs,
                memory_files={"mem.md": evidence},
            )
        )
        assert with_mem.values["fidelity"] == 1.0

    def test_revision_round_scores_feedback(self) -> None:
        a = get_benchmark("streammembench")
        task = a.build_tasks(a.data_type.from_raw(STREAM_RAW))[0]
        data = task.data if isinstance(task.data, dict) else {}
        initial = str(data["initial_user_request"])
        followup = str(data["followup_user_request"])
        outputs = [
            AgentOutput(query=initial, output="不知道"),
            AgentOutput(query=followup, output="不知道"),
            AgentOutput(query=f"revise::{initial}", output=PASSING_STREAM_ANSWER),
        ]
        metrics = a.evaluate(_result(task.name), task, outputs)
        assert metrics["initial_evidence_use"] == 0.0
        assert metrics["feedback_incorporation_applicable"] == 1.0
        assert metrics["feedback_incorporation"] == 1.0

    def test_token_overlap_is_query_coverage(self) -> None:
        assert token_overlap_score("Jake 电脑", "Jake 的工作间有电脑") == 1.0
        assert token_overlap_score("Jake 电脑 硬盘", "Jake") < 0.5


class TestOutputsFromResult:
    def test_qa_uses_last_session(self) -> None:
        task = EvalTask(name="t", data={"qa": [{"question": "drink?", "answer": "latte"}]})
        result = EvalResult(
            task_name="t",
            memory_backend="m",
            session_outcomes=[
                {"session_id": 1, "observation": "ingest"},
                {"session_id": 2, "observation": "latte please"},
            ],
        )
        outs = outputs_from_result(task, result)
        assert len(outs) == 1
        assert outs[0].output == "latte please"

    def test_string_questions_skip_ingest(self) -> None:
        """无 query 映射时的兼容路径（session 数刚好 == question 数才对齐）。"""
        task = EvalTask(
            name="t",
            data={"questions": ["q1", "q2"]},
        )
        result = EvalResult(
            task_name="t",
            memory_backend="m",
            session_outcomes=[
                {"session_id": 1, "observation": "ingest"},
                {"session_id": 2, "observation": "ans1"},
                {"session_id": 3, "observation": "ans2"},
            ],
        )
        outs = outputs_from_result(task, result)
        assert [o.query for o in outs] == ["q1", "q2"]
        assert [o.output for o in outs] == ["ans1", "ans2"]

    def test_exact_query_match_ignores_position(self) -> None:
        """一旦 session_outcomes 带 query（SessionRunner 从 SessionSpec.query 回填），
        对齐走精确匹配，不再依赖"最后 N 个 session"的位置假设。"""
        task = EvalTask(name="t", data={"questions": ["q1", "q2"]})
        result = EvalResult(
            task_name="t",
            memory_backend="m",
            # 顺序打乱 + 中间夹一个非问答 session，位置切片会算错
            session_outcomes=[
                {"session_id": 1, "observation": "ans2", "query": "q2"},
                {"session_id": 2, "observation": "ingest, no query"},
                {"session_id": 3, "observation": "ans1", "query": "q1"},
            ],
        )
        outs = outputs_from_result(task, result)
        by_query = {o.query: o.output for o in outs}
        assert by_query == {"q1": "ans1", "q2": "ans2"}

    def test_travel_session_count_mismatch_no_longer_misaligns(self) -> None:
        """travel 场景：1 个 memory 注入 session + N 个问答 session，
        session 数 != question 数。这是导致旧位置切片错位的真实场景。"""
        a = get_benchmark("memoryarena_travel")
        travel_data = [
            {
                "id": 0,
                "base_person": {"name": "Jennifer", "query": "I prefer window seats."},
                "questions": [
                    {"round_idx": 0, "name": "Eric", "query": "Plan day 1."},
                    {"round_idx": 1, "name": "Eric", "query": "Plan day 2."},
                ],
                "answers": [{"days": 1, "transportation": "Flight F1"}, {"days": 2}],
            }
        ]
        task = a.build_tasks(a.data_type.from_raw(travel_data))[0]
        assert len(task.sessions) == 3  # 1 注入 + 2 问答，session 数 != question 数（2）
        result = EvalResult(
            task_name=task.name,
            memory_backend="m",
            session_outcomes=[
                {"session_id": 1, "observation": "记住了偏好", "query": task.sessions[0].query},
                {"session_id": 2, "observation": "Flight F1", "query": task.sessions[1].query},
                {"session_id": 3, "observation": "Flight F2", "query": task.sessions[2].query},
            ],
        )
        outs = outputs_from_result(task, result)
        by_query = {o.query: o.output for o in outs}
        assert by_query == {"Plan day 1.": "Flight F1", "Plan day 2.": "Flight F2"}


class TestCalculatorRegistry:
    def test_each_dataset_has_own_calculator(self) -> None:
        assert get_benchmark_calculator("memoryarena_shopping").name == "memoryarena_shopping"
        assert get_benchmark_calculator("memoryarena_search").name == "memoryarena_search"
        assert get_benchmark_calculator("memoryarena_math").name == "memoryarena_math"
        assert get_benchmark_calculator("memoryarena_phys").name == "memoryarena_phys"
        assert get_benchmark_calculator("streammembench").name == "streammembench"
