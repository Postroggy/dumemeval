"""测试：agent multi-turn 数据集适配（官方指标，禁止跨数据集 mapping）。"""

import sys
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import dumemeval.datasets.benchmarks  # noqa: F401
from dumemeval.benchmarks.memoryarena.datasets.reasoning import MemoryArenaMathAdapter, MemoryArenaPhysAdapter
from dumemeval.benchmarks.memoryarena.datasets.search import MemoryArenaSearchAdapter
from dumemeval.benchmarks.memoryarena.datasets.travel import MemoryArenaTravelAdapter
from dumemeval.datasets import get_benchmark
from dumemeval.metrics import get_benchmark_calculator, outputs_from_execution
from dumemeval.metrics.benchmarks.streammembench import token_overlap_score
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import AgentOutput, EvalTask, SessionOutcome, TaskExecution
from dumemeval.models.environment import EnvironmentEvidence
from dumemeval.verifier.base import Verdict
from dumemeval.verifier.parsers import parse_judge_response

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


def _scoring_input(
    task: EvalTask, outputs: list[AgentOutput], purchases: list[list[str]] | None = None
) -> MetricInput:
    """Explicit completed fixture sessions; text alone is not execution evidence."""
    return MetricInput(
        task=task,
        outputs=outputs,
        outcomes=[
            SessionOutcome(
                session_id=session.id,
                success=True,
                observation=output.output,
                environment=EnvironmentEvidence(
                    task_id=f"product-{index}",
                    env_name="webshop",
                    operation="step",
                    info={
                        "episode_scope": "session",
                        "purchased_asins": [str(asin) for asin in purchases[index]],
                    },
                )
                if purchases is not None
                else None,
            )
            for index, (session, output) in enumerate(zip(task.sessions, outputs, strict=True))
        ],
    )


class TestMemoryArenaShopping:
    def test_build_uses_question_text(self) -> None:
        a = get_benchmark("memoryarena_shopping")
        task = a.build_tasks(a.data_type.from_raw(SHOPPING_RAW))[0]
        assert task.benchmark == "memoryarena_shopping"
        assert len(task.sessions) == 2
        assert "Buy almond flour B00TUDFEW2" in task.sessions[0].instruction
        # Tool entry points belong to the selected environment, not the task template.
        for session in task.sessions:
            for entry in ("TASK_ENV_URL", "WEBSHOP_ENV_URL", "arena_tool.py", "search[", "click["):
                assert entry not in session.instruction
        assert task.task_environment.get("type") == "webshop"
        assert a.metrics() == ["match_ground_truth", "overall_success", "attribute_match_ratio"]

    def test_subset_and_max_questions(self) -> None:
        from dumemeval.benchmarks.memoryarena.datasets.shopping import MemoryArenaShoppingAdapter

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
        # Issue #4 scores host purchase records, not ASIN mentions in the answer.
        inp = _scoring_input(task, outputs, [["B00TUDFEW2"], ["B08957C9ZH"]])
        metrics = get_benchmark_calculator(a.name).calculate(inp).values
        assert metrics["match_ground_truth"] == 1.0
        assert metrics["overall_success"] == 1.0
        assert "attribute_match" not in metrics
        assert "round_success" not in metrics
        assert "f1" not in metrics
        assert a.evaluate(task, outputs).values == {}

    def test_partial_step_not_overall_success(self) -> None:
        a = get_benchmark("memoryarena_shopping")
        task = a.build_tasks(a.data_type.from_raw(SHOPPING_RAW))[0]
        outputs = [
            AgentOutput(query="Buy almond flour B00TUDFEW2", output="B00TUDFEW2 Almond Flour"),
            AgentOutput(query="Buy muffin pan B08957C9ZH", output="bought something else"),
        ]
        inp = _scoring_input(task, outputs, [["B00TUDFEW2"], ["B000000099"]])
        metrics = get_benchmark_calculator(a.name).calculate(inp).values
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
            mock_verify.return_value = Verdict(
                label="yes",
                score=1.0,
                reason="matches",
                raw="extracted_final_answer: Lagos\ncorrect: yes\nconfidence: 80",
            )
            metrics = get_benchmark_calculator(a.name).calculate(_scoring_input(task, outputs)).values
        # The official search unit is the original final combined query.
        assert mock_verify.call_count == 1
        assert mock_verify.call_args.kwargs["question"] == "Where did they work next?"
        assert metrics["accuracy"] == 1.0
        assert "f1" not in metrics
        assert "match_ground_truth" not in metrics
        assert "round_success" not in metrics

    def test_absent_execution_is_unmeasured_without_calling_llm(self) -> None:
        """No final-query execution means unmeasured, not a measured incorrect answer."""
        a = get_benchmark("memoryarena_search")
        task = a.build_tasks(a.data_type.from_raw(SEARCH_RAW))[0]
        outputs: list[AgentOutput] = []
        with patch("dumemeval.verifier.LLMJudgeVerifier.verify") as mock_verify:
            metrics = a.evaluate(task, outputs)
        assert mock_verify.call_count == 0
        assert metrics.values == {}
        assert metrics.details[0]["score_status"] == "not_measured"

    def test_injected_grader(self) -> None:
        a = MemoryArenaSearchAdapter(judge=lambda pred, gold, _q: gold[:12].lower() in pred.lower())
        task = a.build_tasks(a.data_type.from_raw(SEARCH_RAW))[0]
        outputs = [
            AgentOutput(query="Who started via an audition?", output="Sonia Uche started via an audition."),
            AgentOutput(query="Where did they work next?", output="unrelated"),
        ]
        calculator = get_benchmark_calculator(
            a.name, judge=lambda pred, gold, _q: gold[:12].lower() in pred.lower()
        )
        metrics = calculator.calculate(_scoring_input(task, outputs)).values
        assert metrics["accuracy"] == 0.0  # Correct context cannot offset a wrong final query.

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
        assert a.metrics() == ["is_correct", "avg_progress_score", "overall_average_passrate"]

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
            metrics = a.evaluate(task, outputs)
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
        assert math_a.evaluate(math_task, outputs)["is_correct"] == pytest.approx(0.5)
        assert phys_a.evaluate(phys_task, outputs)["is_correct"] == pytest.approx(0.5)
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
        metrics = a.evaluate(task, outputs)
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
        metrics = a.evaluate(task, outputs)
        assert metrics["initial_evidence_use"] == 0.0
        assert metrics["feedback_incorporation_applicable"] == 1.0
        assert metrics["feedback_incorporation"] == 1.0

    def test_token_overlap_is_query_coverage(self) -> None:
        assert token_overlap_score("Jake 电脑", "Jake 的工作间有电脑") == 1.0
        assert token_overlap_score("Jake 电脑 硬盘", "Jake") < 0.5


def _execution(*sessions: SessionOutcome, name: str = "t") -> TaskExecution:
    return TaskExecution(task_id=name, task_name=name, memory_backend="m", sessions=list(sessions))


class TestOutputsFromExecution:
    def test_qa_uses_last_session(self) -> None:
        task = EvalTask(name="t", data={"qa": [{"question": "drink?", "answer": "latte"}]})
        execution = _execution(
            SessionOutcome(session_id=1, observation="ingest"),
            SessionOutcome(session_id=2, observation="latte please"),
        )
        outs = outputs_from_execution(task, execution)
        assert len(outs) == 1
        assert outs[0].output == "latte please"

    def test_string_questions_skip_ingest(self) -> None:
        """无 query 映射时按位置对齐（session 数刚好 == question 数才准确）。"""
        task = EvalTask(
            name="t",
            data={"questions": ["q1", "q2"]},
        )
        execution = _execution(
            SessionOutcome(session_id=1, observation="ingest"),
            SessionOutcome(session_id=2, observation="ans1"),
            SessionOutcome(session_id=3, observation="ans2"),
        )
        outs = outputs_from_execution(task, execution)
        assert [o.query for o in outs] == ["q1", "q2"]
        assert [o.output for o in outs] == ["ans1", "ans2"]

    def test_exact_query_match_ignores_position(self) -> None:
        """一旦 SessionOutcome.query 有值（SessionRunner 从 SessionSpec.query 回填），
        对齐走精确匹配，不再依赖"最后 N 个 session"的位置假设。"""
        task = EvalTask(name="t", data={"questions": ["q1", "q2"]})
        execution = _execution(
            # 顺序打乱 + 中间夹一个非问答 session，位置切片会算错
            SessionOutcome(session_id=1, observation="ans2", query="q2"),
            SessionOutcome(session_id=2, observation="ingest, no query"),
            SessionOutcome(session_id=3, observation="ans1", query="q1"),
        )
        outs = outputs_from_execution(task, execution)
        by_query = {o.query: o.output for o in outs}
        assert by_query == {"q1": "ans1", "q2": "ans2"}

    def test_travel_session_count_mismatch_no_longer_misaligns(self) -> None:
        """travel 场景：1 个 memory 注入 session + N 个问答 session，
        session 数 != question 数。这是导致旧位置切片错位的真实场景。"""
        a = cast(MemoryArenaTravelAdapter, get_benchmark("memoryarena_travel"))
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
        task = a.build_tasks(a.data_type.from_raw(travel_data), flow="custom")[0]
        assert len(task.sessions) == 3  # 1 注入 + 2 问答，session 数 != question 数（2）
        execution = _execution(
            SessionOutcome(session_id=1, observation="记住了偏好", query=task.sessions[0].query),
            SessionOutcome(session_id=2, observation="Flight F1", query=task.sessions[1].query),
            SessionOutcome(session_id=3, observation="Flight F2", query=task.sessions[2].query),
            name=task.name,
        )
        outs = outputs_from_execution(task, execution)
        by_query = {o.query: o.output for o in outs}
        assert by_query == {"Plan day 1.": "Flight F1", "Plan day 2.": "Flight F2"}


class TestCalculatorRegistry:
    def test_each_dataset_has_own_calculator(self) -> None:
        assert get_benchmark_calculator("memoryarena_shopping").name == "memoryarena_shopping"
        assert get_benchmark_calculator("memoryarena_search").name == "memoryarena_search"
        assert get_benchmark_calculator("memoryarena_math").name == "memoryarena_math"
        assert get_benchmark_calculator("memoryarena_phys").name == "memoryarena_phys"
        assert get_benchmark_calculator("streammembench").name == "streammembench"
