"""Official Travel aggregates and Shopping attributes require completed host evidence."""

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from dumemeval.adapters.directory import DirectoryMemoryAdapter
from dumemeval.benchmarks.memoryarena.datasets.travel import MemoryArenaTravelAdapter
from dumemeval.benchmarks.memoryarena.environment.client import ArenaClient
from dumemeval.benchmarks.memoryarena.environment.config import ArenaRuntimeConfig
from dumemeval.benchmarks.memoryarena.environment.scenarios import ShoppingScenario, TravelScenario
from dumemeval.benchmarks.memoryarena.metrics.shopping import (
    MemoryArenaShoppingCalculator,
    score_attributes,
)
from dumemeval.benchmarks.memoryarena.metrics.travel import MemoryArenaTravelCalculator
from dumemeval.benchmarks.memoryarena.metrics.travel_official import aggregate_groups
from dumemeval.core.protocol import MemorySessionTransferProtocol, TestOnlyProtocol
from dumemeval.execution.executor import SessionExecutor
from dumemeval.lifecycle.memory_transfer import MemoryTransfer
from dumemeval.lifecycle.runner import SessionRunner
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import BenchmarkResult, EvalTask, MemorySpec, SessionOutcome, SessionSpec, TaskExecution
from dumemeval.models.environment import EnvironmentEvidence
from tests.benchmarks.memoryarena.test_contracts import shopping_input


def _plan(name: str, transportation: str) -> str:
    return (
        f"=== {name}'s Plan ===\nDay 1:\nCurrent City: Alpha\n"
        f"Transportation: {transportation}\nBreakfast: -\nAttraction: -\n"
        "Lunch: -\nDinner: -\nAccommodation: -"
    )


def _travel_task() -> EvalTask:
    row = {
        "id": 37,
        "base_person": {
            "name": "Mira",
            "query": "Train trip",
            "daily_plans": [{"days": 1, "transportation": "Bus B1"}],
        },
        "questions": [
            {"round_idx": 1, "name": "Bob", "query": "Plan Bob"},
            {"round_idx": 2, "name": "Cy", "query": "Plan Cy"},
        ],
        "answers": [
            {"round_idx": 1, "daily_plans": [{"days": 1, "transportation": "Train T2"}]},
            {"round_idx": 2, "daily_plans": [{"days": 1, "transportation": "Plane P3"}]},
        ],
    }
    adapter = MemoryArenaTravelAdapter()
    return adapter.build_tasks(adapter.data_type.from_raw([row]))[0]


def _travel_input(task: EvalTask, answers: list[str], *, complete: bool = True) -> MetricInput:
    outcomes = [
        SessionOutcome(
            session_id=session.id,
            success=True,
            observation=answer,
            environment=EnvironmentEvidence(
                task_id="official",
                env_name="travel_planner",
                operation="step",
                session_id=session.id,
                tool="submit",
                info={"history_mode": "memory_on", "history_rounds": session.id - 1},
            ),
        )
        for session, answer in zip(task.sessions, answers, strict=True)
    ]
    if not complete:
        outcomes[-1].environment = None
    return MetricInput(
        task=task,
        execution=TaskExecution(
            task_id=task.name, task_name=task.name, memory_backend="directory", sessions=outcomes
        ),
    )


def test_travel_official_ps_sps_sr_and_missing_evidence() -> None:
    task = _travel_task()
    assert task.data["execution_flow"] == "official_travel"
    assert len(task.sessions) == 2
    scored = MemoryArenaTravelCalculator().calculate(
        _travel_input(task, [_plan("Bob", "Train T2"), _plan("Cy", "Wrong")])
    )
    assert scored.score_scope == "official"
    assert scored.values == {"PS": 50.0, "SPS": 50.0, "SR": 0.0}
    assert [item["person_full_pass"] for item in scored.details] == [True, False]
    failed_execution = _travel_input(task, [_plan("Bob", "Train T2"), _plan("Cy", "Wrong")])
    assert failed_execution.execution is not None
    failed_execution.execution.sessions[0].success = False
    with_submit = MemoryArenaTravelCalculator().calculate(failed_execution)
    assert with_submit.values == scored.values
    assert with_submit.details[0]["execution_status"] == "failed"
    missing = MemoryArenaTravelCalculator().calculate(
        _travel_input(task, [_plan("Bob", "Train T2"), _plan("Cy", "Wrong")], complete=False)
    )
    assert missing.values == {}


def test_travel_cross_group_weighting_matches_official_denominators() -> None:
    groups = [
        BenchmarkResult(
            benchmark="memoryarena_travel",
            values={"PS": 50.0, "SPS": 50.0, "SR": 0.0},
            details=[
                {"person_full_pass": True, "constraint_rate": 1.0},
                {"person_full_pass": False, "constraint_rate": 0.0},
            ],
        ),
        BenchmarkResult(
            benchmark="memoryarena_travel",
            values={"PS": 100.0, "SPS": 100.0, "SR": 100.0},
            details=[{"person_full_pass": True, "constraint_rate": 1.0}],
        ),
    ]
    pooled = aggregate_groups(groups)
    assert pooled.values == {"PS": pytest.approx(200 / 3), "SPS": 75.0, "SR": 50.0}
    assert aggregate_groups([groups[0], groups[1].model_copy(update={"values": {}})]).values == {}


def test_travel_off_history_and_seeded_on_memory(tmp_path: Path) -> None:
    task = _travel_task()
    adapter = DirectoryMemoryAdapter(
        MemorySpec(name="travel", type="directory", path=str(tmp_path / "memory"))
    )
    adapter.setup(task)
    adapter.seed_history(task)
    seed = (adapter.memory_dir / "initial_context.json").read_text(encoding="utf-8")
    assert "Bus B1" in seed and "Mira" in seed

    scenario = TravelScenario(
        task, ArenaRuntimeConfig(reference=tmp_path, env_name="travel_planner"), tmp_path
    )
    first_off = scenario.session_instruction(task.sessions[0], memory_enabled=False)
    first_on = scenario.session_instruction(task.sessions[0], memory_enabled=True)
    assert "Bus B1" in first_off
    assert "Bus B1" not in first_on
    scenario.previous_plans.append(_plan("Bob", "Train T2"))
    scenario.previous_feedback.append("Correct Bob's transportation")
    second_off = scenario.session_instruction(task.sessions[1], memory_enabled=False)
    second_on = scenario.session_instruction(task.sessions[1], memory_enabled=True)
    assert "Train T2" in second_off and "Correct Bob's transportation" in second_off
    assert "Train T2" not in second_on
    entry = scenario.memory_entry(
        EnvironmentEvidence(
            task_id="official",
            env_name="travel_planner",
            operation="step",
            arguments={"answer": _plan("Cy", "Plane P3")},
            info={"history_rounds": 1, "judgement": "Correct"},
        )
    )
    assert entry is not None
    assert json.loads(entry) == {
        "name": "Cy",
        "query": "Plan Cy",
        "scratchpad": "",
        "final_plan": _plan("Cy", "Plane P3"),
        "judgement": "Correct",
    }


@pytest.mark.asyncio
async def test_travel_on_off_history_lifecycle(tmp_path: Path) -> None:
    class CapturedExecutor(SessionExecutor):
        async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
            return SessionOutcome(
                session_id=session.id,
                success=True,
                memory_entry=f'{{"round": {session.id}}}',
            )

    for label, protocol in (
        ("on", MemorySessionTransferProtocol()),
        ("off", TestOnlyProtocol()),
    ):
        task = _travel_task()
        protocol.normalize_sessions(task.sessions)
        root = tmp_path / label
        adapter = DirectoryMemoryAdapter(MemorySpec(name=label, type="directory", path=str(root / "memory")))
        execution = await SessionRunner(
            adapter,
            CapturedExecutor(),
            protocol,
            memory_transfer=MemoryTransfer(root / "transfer", root / "mount"),
            snapshot_dir=root / "snapshots",
        ).run(task)
        assert execution.status == "completed"
        files = {path.name for path in adapter.memory_dir.iterdir()}
        if label == "on":
            assert files == {
                "initial_context.json",
                "official_history_round_1.json",
                "official_history_round_2.json",
            }
        else:
            assert files == set()


@pytest.mark.asyncio
async def test_completed_travel_submission_is_saved_after_other_tool_failure(tmp_path: Path) -> None:
    class FailedExecutor(SessionExecutor):
        async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
            return SessionOutcome(
                session_id=session.id,
                success=False,
                memory_entry=f'{{"round": {session.id}}}',
            )

    task = _travel_task()
    root = tmp_path / "failed"
    adapter = DirectoryMemoryAdapter(MemorySpec(name="failed", type="directory", path=str(root / "memory")))
    await SessionRunner(
        adapter,
        FailedExecutor(),
        MemorySessionTransferProtocol(),
        memory_transfer=MemoryTransfer(root / "transfer", root / "mount"),
        snapshot_dir=root / "snapshots",
    ).run(task)
    assert (adapter.memory_dir / "official_history_round_1.json").exists()
    assert (adapter.memory_dir / "official_history_round_2.json").exists()


def test_shopping_attribute_score_uses_purchased_catalog_name() -> None:
    inp = shopping_input(evidence=True)
    assert inp.execution is not None
    for outcome, asin, name in zip(
        inp.execution.sessions,
        ("B000000001", "B000000002"),
        ("Base-Mixer", "Compatible/Attachment"),
        strict=True,
    ):
        assert outcome.environment is not None
        outcome.environment.info["purchased_products"] = [{"asin": asin, "name": name}]
    result = MemoryArenaShoppingCalculator().calculate(inp)
    assert result.values["attribute_match_ratio"] == 1.0
    assert all(item["attribute_score_status"] == "measured" for item in result.details)
    assert score_attributes(["blue/green", "wireless"], "Blue Green speaker") == (
        0.5,
        ["blue/green"],
        ["wireless"],
    )
    last_evidence = inp.execution.sessions[-1].environment
    assert last_evidence is not None
    last_evidence.info.pop("purchased_products")
    incomplete = MemoryArenaShoppingCalculator().calculate(inp)
    assert "attribute_match_ratio" not in incomplete.values


def test_shopping_unknown_catalog_product_scores_zero_but_lookup_error_is_unmeasured() -> None:
    inp = shopping_input(evidence=True)
    assert inp.execution is not None
    for outcome, asin in zip(inp.execution.sessions, ("B000000001", "B000000002"), strict=True):
        assert outcome.environment is not None
        outcome.environment.info["purchased_products"] = [{"asin": asin, "name": None}]
    unknown = MemoryArenaShoppingCalculator().calculate(inp)
    assert unknown.values["attribute_match_ratio"] == 0.0
    assert all(item["attribute_score_status"] == "measured" for item in unknown.details)
    last_evidence = inp.execution.sessions[-1].environment
    assert last_evidence is not None
    last_evidence.info["attribute_lookup_error"] = "RuntimeError"
    failed_lookup = MemoryArenaShoppingCalculator().calculate(inp)
    assert "attribute_match_ratio" not in failed_lookup.values


def test_shopping_full_reward_and_llm_attribute_evidence() -> None:
    inp = shopping_input(evidence=True)
    assert inp.execution is not None
    for outcome, reward, attribute_ratio in zip(inp.execution.sessions, (0.4, 1.0), (0.0, 1.0), strict=True):
        assert outcome.environment is not None
        outcome.environment.info["attribute_mode"] = "llm"
        outcome.environment.info["official_reward"] = {
            "reward": reward,
            "success": reward == 1.0,
            "purchased_name": "Catalog product",
            "components": {
                "attr_match_ratio": attribute_ratio,
                "matched_attributes": [] if not attribute_ratio else ["required"],
                "missing_attributes": ["required"] if not attribute_ratio else [],
                "attribute_judge": {"used_llm": True, "attempts": 1},
            },
            "calculation": {"final_reward": reward},
        }
    scored = MemoryArenaShoppingCalculator().calculate(inp)
    assert scored.values["average_reward"] == pytest.approx(0.7)
    assert scored.values["reward_item_success"] == 0.0
    assert scored.values["attribute_match_ratio"] == 0.5
    assert all(item["attribute_mode"] == "llm" for item in scored.details)
    assert all(item["reward_components"]["attribute_judge"]["used_llm"] for item in scored.details)


def test_shopping_pooled_reward_weights_steps_and_items() -> None:
    calculator = MemoryArenaShoppingCalculator()
    results = [
        BenchmarkResult(
            benchmark="memoryarena_shopping",
            values={
                "match_ground_truth": 0.5,
                "overall_success": 0.0,
                "attribute_match_ratio": 0.5,
                "average_reward": 0.5,
                "reward_item_success": 0.0,
            },
            details=[
                {
                    "score_status": "measured",
                    "match_ground_truth": True,
                    "reward": 1.0,
                    "attribute_score_status": "measured",
                    "attribute_match_ratio": 1.0,
                },
                {
                    "score_status": "measured",
                    "match_ground_truth": False,
                    "reward": 0.0,
                    "attribute_score_status": "measured",
                    "attribute_match_ratio": 0.0,
                },
            ],
        ),
        BenchmarkResult(
            benchmark="memoryarena_shopping",
            values={
                "match_ground_truth": 1.0,
                "overall_success": 1.0,
                "attribute_match_ratio": 1.0,
                "average_reward": 1.0,
                "reward_item_success": 1.0,
            },
            details=[
                {
                    "score_status": "measured",
                    "match_ground_truth": True,
                    "reward": 1.0,
                    "attribute_score_status": "measured",
                    "attribute_match_ratio": 1.0,
                },
            ],
        ),
    ]
    pooled = calculator.aggregate(results)
    assert pooled is not None
    assert pooled.values == {
        "match_ground_truth": pytest.approx(2 / 3),
        "overall_success": 0.5,
        "attribute_match_ratio": pytest.approx(2 / 3),
        "average_reward": pytest.approx(2 / 3),
        "reward_item_success": 0.5,
    }


def test_shopping_scenario_requests_pinned_full_reward(tmp_path: Path) -> None:
    inp = shopping_input(evidence=True)
    assert inp.task is not None
    scenario = ShoppingScenario(
        inp.task,
        ArenaRuntimeConfig(
            reference=tmp_path,
            env_name="webshop",
            shopping_attribute_mode="llm",
            shopping_attribute_model="judge-model",
        ),
        tmp_path,
    )
    client_mock = MagicMock(spec=ArenaClient)
    client_mock.observation.return_value = EnvironmentEvidence(
        task_id="official",
        env_name="webshop",
        operation="get_observation",
        observation={"purchases": [{"asin": "B000000001", "price": 12.0}]},
    )
    client_mock.shopping_product.return_value = "Product name"
    client_mock.shopping_reward.return_value = {
        "attribute_mode": "llm",
        "reward": {"reward": 0.75, "components": {"attr_match_ratio": 0.5}},
    }
    official_step = {
        "step": 1,
        "target_asin": "B000000001",
        "requirements": {"attributes": ["Base Mixer"], "price_constraints": {}},
    }
    (tmp_path / f"official-task-{inp.task.sessions[0].id}.json").write_text(
        json.dumps({"steps": [official_step]}), encoding="utf-8"
    )
    evidence = scenario.submit(cast(ArenaClient, client_mock), inp.task.sessions[0], "done")
    assert evidence.info["official_reward"] == client_mock.shopping_reward.return_value["reward"]
    assert evidence.info["attribute_mode"] == "llm"
    args, kwargs = client_mock.shopping_reward.call_args
    assert args[0] == {"step": 1, "purchased_asin": "B000000001", "purchased_price": 12.0}
    assert args[1] == official_step
    assert kwargs == {"attribute_mode": "llm", "attribute_model": "judge-model"}
