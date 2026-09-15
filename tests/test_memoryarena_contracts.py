"""Offline task, evidence, and ablation regressions for issue #4."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from dumemeval.adapters.none import NoneMemoryAdapter
from dumemeval.core.protocol import TestOnlyProtocol
from dumemeval.datasets.benchmarks.memoryarena_reasoning import MemoryArenaMathAdapter, MemoryArenaPhysAdapter
from dumemeval.datasets.benchmarks.memoryarena_search import MemoryArenaSearchAdapter
from dumemeval.datasets.benchmarks.memoryarena_shopping import MemoryArenaShoppingAdapter
from dumemeval.datasets.benchmarks.memoryarena_travel import MemoryArenaTravelAdapter
from dumemeval.execution.executor import SessionExecutor
from dumemeval.lifecycle.memory_transfer import MemoryTransfer
from dumemeval.lifecycle.runner import SessionRunner
from dumemeval.metrics.benchmarks.memoryarena_shopping import MemoryArenaShoppingCalculator
from dumemeval.metrics.core.base import MetricInput, round_items
from dumemeval.models import EvalTask, MemorySpec, SampleResult, SessionOutcome, SessionSpec, TaskExecution
from dumemeval.models.environment import EnvironmentEvidence

FIXTURES = Path(__file__).parent / "fixtures" / "memoryarena" / "cases.json"
ADAPTERS = {
    "shopping": MemoryArenaShoppingAdapter,
    "travel": MemoryArenaTravelAdapter,
    "search": MemoryArenaSearchAdapter,
    "math": MemoryArenaMathAdapter,
    "phys": MemoryArenaPhysAdapter,
}


def raw_case(name: str) -> list[dict[str, Any]]:
    cases: dict[str, list[dict[str, Any]]] = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return cases[name]


@pytest.mark.parametrize("name", ADAPTERS)
def test_five_scenarios_keep_identity_order_and_sampling(name: str) -> None:
    adapter = ADAPTERS[name]()
    task = adapter.build_tasks(adapter.data_type.from_raw(raw_case(name)), subset=1, max_questions=1)[0]
    assert task.name == f"memoryarena_{name}_37"
    assert task.data["source_round_count"] == 2
    assert len(task.data["questions"]) == len(task.data["answers"]) == 1
    scored = [session for session in task.sessions if session.query is not None]
    assert len(scored) == 1
    assert scored[0].query == raw_case(name)[0]["questions"][0]


@pytest.mark.parametrize("name", ADAPTERS)
def test_misaligned_answers_fail_before_execution(name: str) -> None:
    adapter = ADAPTERS[name]()
    rows = raw_case(name)
    rows[0]["answers"].pop()
    with pytest.raises(ValueError, match="equal lengths"):
        adapter.data_type.from_raw(rows)


@pytest.mark.parametrize("name", ADAPTERS)
def test_duplicate_memory_namespaces_are_rejected(name: str) -> None:
    adapter = ADAPTERS[name]()
    rows = raw_case(name)
    with pytest.raises(ValueError, match="unique"):
        adapter.data_type.from_raw(rows * 2)


@pytest.mark.parametrize("name", ADAPTERS)
@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_sampling_is_not_silently_treated_as_full_dataset(name: str, limit: int) -> None:
    adapter = ADAPTERS[name]()
    with pytest.raises(ValueError, match="positive"):
        adapter.build_tasks(adapter.data_type.from_raw(raw_case(name)), max_questions=limit)


def test_travel_hf_names_base_plan_and_indexed_answer_alignment() -> None:
    adapter = MemoryArenaTravelAdapter()
    task = adapter.build_tasks(adapter.data_type.from_raw(raw_case("travel")))[0]
    assert "Train T1" in task.sessions[0].instruction
    assert task.data["questions"][0]["name"] == "Bob"
    assert task.data["questions"][0]["round_idx"] == 1
    assert "=== Bob's Plan ===" in task.sessions[1].instruction
    rows = raw_case("travel")
    rows[0]["questions"] = [
        {"round_idx": 9, "name": "Bob", "query": "first"},
        {"round_idx": 12, "name": "Cy", "query": "second"},
    ]
    rows[0]["answers"] = [{"round_idx": 12, "daily_plans": []}, {"round_idx": 9, "daily_plans": []}]
    aligned = adapter.build_tasks(adapter.data_type.from_raw(rows))[0]
    assert [answer["round_idx"] for answer in aligned.data["answers"]] == [9, 12]


def test_reasoning_rejects_missing_background() -> None:
    adapter = MemoryArenaMathAdapter()
    rows = raw_case("math")
    rows[0]["backgrounds"].pop()
    with pytest.raises(ValueError, match="backgrounds"):
        adapter.data_type.from_raw(rows)


def shopping_input(*, evidence: bool, wrong: bool = False) -> MetricInput:
    adapter = MemoryArenaShoppingAdapter()
    task = adapter.build_tasks(adapter.data_type.from_raw(raw_case("shopping")))[0]
    outcomes = []
    for i in range(2):
        purchased: list[JsonValue] = ["B000000001", "B000000002"]
        purchased = ["WRONG"] if wrong else purchased[: i + 1]
        outcomes.append(
            SessionOutcome(
                session_id=i + 1,
                success=True,
                observation="I bought B000000001 and B000000002",
                environment=EnvironmentEvidence(
                    task_id="owned-test-environment",
                    env_name="webshop",
                    operation="step",
                    info={"purchased_asins": purchased},
                )
                if evidence
                else None,
            )
        )
    return MetricInput(
        task=task,
        execution=TaskExecution(
            task_id=task.name, task_name=task.name, memory_backend="none", sessions=outcomes
        ),
    )


def test_shopping_narrative_cannot_fabricate_purchase() -> None:
    result = MemoryArenaShoppingCalculator().calculate(shopping_input(evidence=False))
    assert result.values == {}
    assert all(detail["official_score"] is None for detail in result.details)


def test_shopping_zero_is_distinct_from_missing_evidence() -> None:
    result = MemoryArenaShoppingCalculator().calculate(shopping_input(evidence=True, wrong=True))
    assert result.values["match_ground_truth"] == 0
    assert result.values["overall_success"] == 0
    assert all(detail["score_status"] == "measured" for detail in result.details)


def test_shopping_cumulative_purchases_and_incomplete_bundle() -> None:
    inp = shopping_input(evidence=True)
    result = MemoryArenaShoppingCalculator().calculate(inp)
    assert result.values == {"match_ground_truth": 1, "overall_success": 1}
    inp.task.data["source_round_count"] = 3
    assert "overall_success" not in MemoryArenaShoppingCalculator().calculate(inp).values


def test_same_question_in_two_rounds_uses_session_identity() -> None:
    task = EvalTask(
        name="repeated",
        sessions=[SessionSpec(id=i, instruction="q", query="q") for i in (1, 2)],
        data={"questions": ["q", "q"], "answers": ["a", "b"]},
    )
    inp = MetricInput(
        task=task,
        execution=TaskExecution(task_id="repeated", task_name="repeated", memory_backend="none"),
        samples=[
            SampleResult(sample_id="1", session_id=1, query="q", response="a"),
            SampleResult(sample_id="2", session_id=2, query="q", response="b"),
        ],
    )
    assert [row[-1] for row in round_items(inp)] == ["a", "b"]
    inp.samples.pop(0)
    assert [row[-1] for row in round_items(inp)] == ["", "b"]


class CaptureExecutor(SessionExecutor):
    def __init__(self) -> None:
        self.suffixes: list[str] = []

    async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
        self.suffixes.append(session_ctx["instruction_suffix"])
        assert session_ctx["agent_env"]["TASK_ENV_URL"] == "http://localhost:8001"
        return SessionOutcome(session_id=session.id, success=session.id == 1, observation="fixture output")


async def test_memory_disabled_preserves_environment_access(tmp_path: Path) -> None:
    task = EvalTask(
        name="baseline",
        sessions=[SessionSpec(id=i, instruction="q", memory_inject=False) for i in (1, 2)],
        task_environment={"type": "webshop", "base_url": "http://localhost:8001"},
        memory_instruction="proactive",
    )
    executor = CaptureExecutor()
    runner = SessionRunner(
        NoneMemoryAdapter(MemorySpec(name="none", type="none")),
        executor,
        TestOnlyProtocol(),
        memory_transfer=MemoryTransfer(tmp_path / "transfer"),
        snapshot_dir=tmp_path / "snapshots",
    )
    result = await runner.run(task)
    assert all("/env/step" in suffix for suffix in executor.suffixes)
    assert all("[持久记忆]" not in suffix for suffix in executor.suffixes)
    assert result.status == "partial"


async def test_memory_hint_does_not_leak_into_non_injecting_session(tmp_path: Path) -> None:
    from dumemeval.adapters.directory import DirectoryMemoryAdapter

    task = EvalTask(
        name="mixed",
        sessions=[
            SessionSpec(id=1, instruction="q"),
            SessionSpec(id=2, instruction="q", memory_inject=False),
        ],
        task_environment={"type": "webshop", "base_url": "http://localhost:8001"},
        memory_instruction="proactive",
    )
    executor = CaptureExecutor()
    adapter = DirectoryMemoryAdapter(MemorySpec(name="directory", path=str(tmp_path / "memory")))
    runner = SessionRunner(
        adapter,
        executor,
        memory_transfer=MemoryTransfer(tmp_path / "transfer"),
        snapshot_dir=tmp_path / "snapshots",
    )
    await runner.run(task)
    assert "[持久记忆]" in executor.suffixes[0]
    assert "[持久记忆]" not in executor.suffixes[1]
    assert all("/env/step" in suffix for suffix in executor.suffixes)
