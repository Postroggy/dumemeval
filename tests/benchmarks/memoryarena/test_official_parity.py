"""Compare against pinned official functions without vendoring upstream code.

Set MEMORYARENA_REFERENCE to a local checkout. These tests exercise scorers with
fixed inputs, not the official environment/agent or a real judge model.
"""

from __future__ import annotations

import ast
import difflib
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dumemeval.benchmarks.memoryarena.metrics.reasoning import parse_math_judge_output
from dumemeval.benchmarks.memoryarena.metrics.travel import (
    SLOTS,
    evaluate_slots,
    format_judge_answer,
    format_judge_hint,
    parse_person_plan,
    slot_similarity,
)
from dumemeval.verifier.parsers import parse_judge_response

COMMIT = "6cd9de14b71915e39ac742a20dc33785e14b6aab"


@pytest.fixture(scope="module")
def official_root() -> Path:
    configured = os.environ.get("MEMORYARENA_REFERENCE")
    if not configured:
        pytest.skip("Official scorer parity not run: set MEMORYARENA_REFERENCE to the pinned checkout")
    root = Path(configured)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    assert revision == COMMIT, "Official reference must match the recorded source lock"
    dirty = subprocess.check_output(["git", "diff", "HEAD", "--", "env"], cwd=root, text=True)
    assert not dirty, "Official scorer source has local modifications"
    return root


def definitions(path: Path, names: set[str], class_name: str | None = None) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = tree.body
    if class_name:
        nodes = next(
            node.body for node in nodes if isinstance(node, ast.ClassDef) and node.name == class_name
        )
    selected = [node for node in nodes if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == names
    module = ast.Module(
        body=[*ast.parse("from __future__ import annotations").body, *selected], type_ignores=[]
    )
    namespace: dict[str, Any] = {
        "re": re,
        "difflib": difflib,
        "SLOTS": SLOTS,
        "SIM_TH": 0.7,
        "HINT_SIM_TH": 0.9,
    }
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def test_paper_weighted_aggregation_matches_official(official_root: Path, tmp_path: Path) -> None:
    import numpy as np
    import tiktoken

    from dumemeval.benchmarks.memoryarena.metrics.reasoning_aggregation import aggregate_papers
    from dumemeval.models import BenchmarkResult

    official = definitions(
        official_root / "env/env_systems/formal_reasoning_env/eval.py",
        {"get_passrate_at_k", "print_result"},
    )
    official.update(np=np, tiktoken=tiktoken, os=os, json=json)
    # Unequal lengths expose accidental micro-averaging of paper progress.
    papers = [[True, False], [False, True, True, True], [False]]
    data = {str(i): ([{"is_correct": flag} for flag in paper], len(paper)) for i, paper in enumerate(papers)}
    logger = logging.getLogger(__name__)
    official["print_result"](*official["get_passrate_at_k"](data, logger), str(tmp_path), logger)
    expected = json.loads((tmp_path / "all_results.json").read_text())
    actual = aggregate_papers(
        [
            BenchmarkResult(
                benchmark="memoryarena_math",
                values={"overall_average_passrate": float(paper[-1])},
                details=[{"is_correct": flag, "score_status": "measured"} for flag in paper],
            )
            for paper in papers
        ]
    )
    for key in ("overall_average_passrate", "avg_progress_score"):
        assert actual.values[key] == pytest.approx(expected[key])
    for key in (
        "min_k",
        "passrate_at_k",
        "cummulative_passrate_at_k",
        "passrate_at_min_k",
        "cummulative_passrate_at_min_k",
    ):
        assert actual.details[-1][key] == pytest.approx(expected[key])


@pytest.mark.parametrize("correct", [True, False])
@pytest.mark.parametrize("style", ["plain", "bold_colon", "bold_label"])
def test_search_grader_parser_matches_official(official_root: Path, correct: bool, style: str) -> None:
    labels = {"plain": "{key}:", "bold_colon": "**{key}:**", "bold_label": "**{key}**:"}
    raw = "\n".join(
        f"{labels[style].format(key=key)} {value}"
        for key, value in {
            "extracted_final_answer": "Ada",
            "reasoning": "A fixed explanation.",
            "correct": "yes" if correct else "no",
            "confidence": "84.5%",
        }.items()
    )
    official = definitions(
        official_root / "env/env_systems/web_search_env/evaluate_with_openai.py", {"parse_judge_response"}
    )
    assert parse_judge_response(raw) == official["parse_judge_response"](raw)


@pytest.mark.parametrize("raw", ["", "unparseable", "correct: no\nconfidence: 101%"])
def test_search_missing_and_malformed_judgements(official_root: Path, raw: str) -> None:
    official = definitions(
        official_root / "env/env_systems/web_search_env/evaluate_with_openai.py", {"parse_judge_response"}
    )
    assert parse_judge_response(raw) == official["parse_judge_response"](raw)


def test_search_final_query_and_aggregation_match_official(official_root: Path) -> None:
    from dumemeval.pipeline.metrics_run import pool_benchmark
    from tests.benchmarks.memoryarena.test_search_scoring import score_search, search_task

    summarize = definitions(official_root / "run_search.py", {"_summarize_single_result"})[
        "_summarize_single_result"
    ]
    cases = [[False, True], [True, True, True, False]]
    results = []
    expected = []
    for flags in cases:
        result = score_search(search_task(len(flags)), flags, [])
        official = summarize({"query_id": len(flags), "judgement": {"correct": flags[-1]}})
        assert result.values["accuracy"] == official["accuracy"]
        results.append(result)
        expected.append(official["accuracy"])
    assert pool_benchmark(results, []).values["accuracy"] == sum(expected) / len(expected)


@pytest.mark.parametrize("scenario", ["math", "phys"])
@pytest.mark.parametrize("raw", ["yes", "NO", "Yesterday", "", "no, yes"])
def test_reasoning_judge_parsing_matches_shared_official_environment(
    official_root: Path, scenario: str, raw: str
) -> None:
    official = definitions(official_root / "env/env_systems/math_env.py", {"judge"}, "MathEnvironment")
    backend = SimpleNamespace(chat=lambda **kwargs: raw)
    env = SimpleNamespace(llm_backend=backend, temperature=0)
    correct, text = official["judge"](env, "candidate", "reference", "question")
    assert parse_math_judge_output(raw) == correct, scenario
    assert text == raw.lower()


@pytest.mark.parametrize(
    "text",
    [
        "=== Bob's Plan ===\nDay 1:\nCurrent City: Alpha",
        "Day 1:\nCurrent City: Alpha",
        "=== Cy's Plan ===\nDay 1:\nCurrent City: Alpha",
        "",
    ],
)
def test_travel_parser_slots_and_feedback_match_official(official_root: Path, text: str) -> None:
    path = official_root / "env/env_systems/travel_env.py"
    official = definitions(
        path,
        {
            "_similarity",
            "_get_day",
            "_parse_person_plan_from_result",
            "_format_judge_hint",
            "_format_judge_answer",
        },
    )
    evaluate = definitions(path, {"_evaluate_slots"}, "TravelPlannerEnvironment")["_evaluate_slots"]
    evaluate.__globals__.update({name: official[name] for name in ("_get_day", "_similarity")})
    gold = [{"days": 1, "current_city": "Alpha"}]
    plan = parse_person_plan(text, "Bob")
    assert plan == official["_parse_person_plan_from_result"](text, "Bob")
    assert evaluate_slots(plan, gold) == evaluate(None, plan, gold)
    assert format_judge_hint("Bob", plan, gold) == official["_format_judge_hint"]("Bob", plan, gold)
    assert format_judge_answer("Bob", gold) == official["_format_judge_answer"]("Bob", gold)
    for left, right in [("Alpha", "alphabet"), ("-", "-"), ("", "Alpha"), ("Train T1", "train t1")]:
        assert slot_similarity(left, right) == official["_similarity"](left, right)


@pytest.mark.parametrize("purchased", [[], ["B000000001"], ["WRONG"], ["B000000001", "B000000002"]])
def test_shopping_exact_purchase_rule_matches_official(official_root: Path, purchased: list[str]) -> None:
    from dumemeval.benchmarks.memoryarena.metrics.shopping import MemoryArenaShoppingCalculator
    from tests.benchmarks.memoryarena.test_contracts import shopping_input

    methods = definitions(
        official_root / "env/env_systems/webshop_env.py",
        {"_normalize_expected_asins", "_build_judgement"},
        "WebShopEnvironment",
    )
    env = SimpleNamespace(
        task_def={"target_products": ["B000000002"]},
        _get_client=lambda: SimpleNamespace(purchased_asins=purchased),
    )
    env._normalize_expected_asins = lambda gold: methods["_normalize_expected_asins"](env, gold)
    official = methods["_build_judgement"](env, env.task_def["target_products"])
    inp = shopping_input(evidence=True)
    assert inp.execution is not None
    assert inp.task is not None
    last = inp.execution.sessions[-1].environment
    assert last is not None
    last.info["purchased_asins"] = list(purchased)
    last.info["episode_scope"] = "session"
    result = MemoryArenaShoppingCalculator().calculate(inp)
    assert result.details[-1]["match_ground_truth"] == official["match_ground_truth"]


@pytest.mark.parametrize(
    "purchases", [["B000000099", "B000000002"], [None, "B000000002"], ["B000000001", "B000000002"]]
)
def test_shopping_per_product_and_bundle_match_official_runner(
    official_root: Path, purchases: list[str | None]
) -> None:
    from dumemeval.benchmarks.memoryarena.metrics.shopping import MemoryArenaShoppingCalculator
    from tests.benchmarks.memoryarena.test_contracts import shopping_input

    official = definitions(
        official_root / "env/env_systems/web_shopping_env/runtime/runner/summary_build.py",
        {"hydrate_step_summary"},
    )
    official.update(get_product_name_from_catalog=lambda asin: asin, format_feedback=lambda *args: "")
    enrich = definitions(official_root / "run_shopping.py", {"enrich_task_result"})["enrich_task_result"]
    inp = shopping_input(evidence=True)
    assert inp.execution is not None
    assert inp.task is not None
    steps = []
    for index, purchased in enumerate(purchases):
        evidence = inp.execution.sessions[index].environment
        assert evidence is not None
        evidence.task_id = f"episode-{index}"
        evidence.info.update(
            episode_scope="session", purchased_asins=[] if purchased is None else [purchased]
        )
        steps.append(
            official["hydrate_step_summary"](
                {"purchased_asin": purchased, "match_ground_truth": None if purchased else False},
                inp.task.data["answers"][index],
                index + 1,
            )
        )
    expected = enrich({"steps": steps, "total_steps": 2})
    actual = MemoryArenaShoppingCalculator().calculate(inp)
    assert [d["match_ground_truth"] for d in actual.details] == [s["match_ground_truth"] for s in steps]
    assert actual.values["match_ground_truth"] == expected["matched_steps"] / 2
    assert actual.values["overall_success"] == expected["overall_success"]


def test_shopping_split_task_http_uses_official_task_builder(official_root: Path, tmp_path: Path) -> None:
    import copy

    from dumemeval.benchmarks.memoryarena.environment.client import ArenaClient
    from dumemeval.benchmarks.memoryarena.environment.config import ArenaConnection, ArenaRuntimeConfig
    from dumemeval.benchmarks.memoryarena.environment.service import OfficialService
    from tests.benchmarks.memoryarena.test_contracts import raw_case

    row = raw_case("shopping")[0]
    row["questions"] = ["Rules\nProduct 1:\nBuy a base.", "Rules\nProduct 2:\nBuy an attachment."]
    official = definitions(
        official_root / "env/env_systems/web_shopping_env/runtime/runner/task_files.py",
        {
            "_reconstruct_task_def_from_hf_row",
            "split_agent_instruction",
            "build_instruction_for_step",
            "build_single_step_task",
        },
    )
    official["copy"] = copy
    full = official["_reconstruct_task_def_from_hf_row"](row)
    prefix, sections = official["split_agent_instruction"](full["agent_instruction"])
    service = OfficialService(
        ArenaRuntimeConfig(reference=official_root, env_name="webshop"), tmp_path / "service"
    )
    try:
        service.start()
        client = ArenaClient(ArenaConnection(base_url=service.url, env_name="webshop"))
        try:
            for index in range(2):
                path = tmp_path / f"step-{index}.json"
                client.shopping_task(row, str(path), step_index=index)
                instruction = official["build_instruction_for_step"](
                    prefix, sections, index + 1, {}, include_history=False
                )
                expected = official["build_single_step_task"](full, index, instruction)
                assert json.loads(path.read_text(encoding="utf-8")) == expected
                assert expected["target_products"] == [row["answers"][index]["target_asin"]]
                assert expected["global_constraints"]["max_steps"] == 1
        finally:
            client.close()
    finally:
        service.close()
