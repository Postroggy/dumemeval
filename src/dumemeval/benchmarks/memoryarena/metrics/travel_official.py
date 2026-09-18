"""Pinned MemoryArena Travel evaluator's six-slot PS/SPS/SR aggregation.

Source: https://github.com/ZexueHe/MemoryArena/blob/6cd9de14b71915e39ac742a20dc33785e14b6aab/env/env_systems/travel_planner_env/eval.py
"""

from __future__ import annotations

import difflib
from typing import Any

from dumemeval.models import BenchmarkResult

SIM_TH = 0.7
OFFICIAL_SLOTS = (
    "breakfast",
    "lunch",
    "dinner",
    "accommodation",
    "transportation",
    "attraction",
)


def _similarity(left: Any, right: Any) -> float:
    """Pinned evaluator's six-slot string similarity."""
    if not left or not right:
        return 0.0
    a, b = str(left).strip().lower(), str(right).strip().lower()
    if a == "-" and b == "-":
        return 1.0
    length = min(len(a), len(b))
    return difflib.SequenceMatcher(None, a[:length], b[:length]).ratio() if length else 0.0


def _get_day(plan: list[dict[str, Any]], day_idx: Any) -> dict[str, Any] | None:
    for day in plan:
        if day.get("day") == day_idx or day.get("days") == day_idx:
            return day
    return None


def person_result(
    ground_truth: list[dict[str, Any]],
    submitted: list[dict[str, Any]],
    base_plan: list[dict[str, Any]],
) -> tuple[bool, float | None]:
    """Return full-person pass and the constrained-slot rate from the official evaluator."""
    if not ground_truth or not submitted:
        full_pass = False
    else:
        full_pass = True
        for gt_day in ground_truth:
            day_idx = gt_day.get("days") or gt_day.get("day")
            sub_day = _get_day(submitted, day_idx)
            if not sub_day:
                full_pass = False
                break
            if any(
                _similarity(gt_day.get(slot, "-"), sub_day.get(slot, "-")) < SIM_TH for slot in OFFICIAL_SLOTS
            ):
                full_pass = False
                break

    constrained = 0
    passed = 0
    for gt_day in ground_truth:
        day_idx = gt_day.get("days") or gt_day.get("day")
        base_day = _get_day(base_plan, day_idx)
        if not base_day:
            continue
        for slot in OFFICIAL_SLOTS:
            if _similarity(base_day.get(slot, "-"), gt_day.get(slot, "-")) >= SIM_TH:
                continue
            constrained += 1
            sub_day = _get_day(submitted, day_idx)
            if sub_day and _similarity(gt_day.get(slot, "-"), sub_day.get(slot, "-")) >= SIM_TH:
                passed += 1
    return full_pass, passed / constrained if constrained else None


def group_values(details: list[dict[str, Any]]) -> dict[str, float]:
    """Official percentages for one complete submitted group."""
    if not details or any(item.get("score_status") != "measured" for item in details):
        return {}
    rates = [float(item["constraint_rate"]) for item in details if item.get("constraint_rate") is not None]
    return {
        "PS": 100.0 * sum(bool(item["person_full_pass"]) for item in details) / len(details),
        "SPS": 100.0 * sum(rates) / len(rates) if rates else 0.0,
        "SR": 100.0 * float(all(item["person_full_pass"] for item in details)),
    }


def aggregate_groups(results: list[BenchmarkResult]) -> BenchmarkResult:
    """Weight PS by persons, SPS by groups with constraints, and SR by groups."""
    pooled = BenchmarkResult(
        benchmark="memoryarena_travel",
        score_scope="official",
        primary_metric="PS",
        details=[item for result in results for item in result.details],
    )
    if not results or any(not {"PS", "SPS", "SR"} <= result.values.keys() for result in results):
        return pooled
    details = pooled.details
    rates_by_group = [
        [float(item["constraint_rate"]) for item in result.details if item.get("constraint_rate") is not None]
        for result in results
    ]
    group_rates = [sum(rates) / len(rates) for rates in rates_by_group if rates]
    pooled.values = {
        "PS": 100.0 * sum(bool(item["person_full_pass"]) for item in details) / len(details),
        "SPS": 100.0 * sum(group_rates) / len(group_rates) if group_rates else 0.0,
        "SR": sum(result.values["SR"] for result in results) / len(results),
    }
    return pooled
