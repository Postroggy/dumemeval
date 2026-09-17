"""MemoryArena travel 官方指标：slot 相似度 + judgement_mode（hint / answer / none）。

对齐 vendors/MemoryArena/env/env_systems/travel_env.py：
- 成功判定：_evaluate_slots（slot 相似度 ≥ 0.7），不是「有输出就算成功」
- judgement_mode=hint → 只指出需要改正的 slot
- judgement_mode=answer → 给出完整 reference plan
- judgement_mode=none → 只打分，不生成反馈
"""

from __future__ import annotations

import difflib
import re
from typing import Any, ClassVar, Literal

from dumemeval.metrics.core.base import (
    MetricBundle,
    MetricCalculator,
    MetricInput,
    MetricKind,
    outcome_for_round,
    round_items,
)

SLOTS = [
    "current_city",
    "transportation",
    "breakfast",
    "attraction",
    "lunch",
    "dinner",
    "accommodation",
]
SIM_TH = 0.7
HINT_SIM_TH = 0.9

JudgementMode = Literal["hint", "answer", "none"]


def slot_similarity(left: Any, right: Any) -> float:
    """官方 _similarity。"""
    if not left or not right:
        return 0.0
    a, b = str(left).strip().lower(), str(right).strip().lower()
    if a == "-" and b == "-":
        return 1.0
    length = min(len(a), len(b))
    return difflib.SequenceMatcher(None, a[:length], b[:length]).ratio() if length else 0.0


def _get_day(plan: list[dict[str, Any]], day_idx: Any) -> dict[str, Any] | None:
    if not plan:
        return None
    for day in plan:
        if day.get("day") == day_idx or day.get("days") == day_idx:
            return day
    return None


def parse_person_plan(result_text: str, name: str) -> list[dict[str, Any]]:
    """官方 _parse_person_plan_from_result。"""
    if not result_text:
        return []
    if name:
        pattern = rf"===\s*{re.escape(name)}'s Plan\s*===(.*?)(?====|$)"
        match = re.search(pattern, result_text, re.DOTALL)
        if not match:
            return []
        plan_text = match.group(1).strip()
    else:
        plan_text = result_text
    days: list[dict[str, Any]] = []
    for day_match in re.finditer(r"Day\s*(\d+):(.*?)(?=Day\s*\d+:|$)", plan_text, re.DOTALL):
        day_obj: dict[str, Any] = {"day": int(day_match.group(1))}
        for line in day_match.group(2).strip().split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                day_obj[key.strip().lower().replace(" ", "_")] = val.strip()
        days.append(day_obj)
    return days


def _as_daily_plans(ground_truth: Any, fallback_name: str = "") -> tuple[str, list[dict[str, Any]]]:
    """把 adapter 里多种 GT 形态归一成 (name, daily_plans)。"""
    if isinstance(ground_truth, dict):
        name = str(ground_truth.get("name") or fallback_name)
        if isinstance(ground_truth.get("daily_plans"), list):
            return name, list(ground_truth["daily_plans"])
        if any(key in ground_truth for key in [*SLOTS, "days", "day"]):
            return name, [ground_truth]
        return name, []
    if isinstance(ground_truth, list):
        return fallback_name, [item for item in ground_truth if isinstance(item, dict)]
    return fallback_name, []


def evaluate_slots(model_plan: list[dict[str, Any]], gt_plans: list[dict[str, Any]]) -> bool:
    """官方 _evaluate_slots：任一天任一 slot 相似度 < 0.7 → 失败。"""
    if not gt_plans:
        return False
    for gt_day in gt_plans:
        day_idx = gt_day.get("days") if gt_day.get("days") is not None else gt_day.get("day")
        sub_day = _get_day(model_plan, day_idx)
        if not sub_day:
            return False
        for slot in SLOTS:
            expected = gt_day.get(slot, "-")
            actual = sub_day.get(slot, "-")
            if slot_similarity(expected, actual) < SIM_TH:
                return False
    return True


def slot_match_rate(model_plan: list[dict[str, Any]], gt_plans: list[dict[str, Any]]) -> float:
    """slot 级命中率（辅助指标；round_success 仍走官方全槽位阈值）。"""
    total = 0
    matched = 0
    for gt_day in gt_plans:
        day_idx = gt_day.get("days") if gt_day.get("days") is not None else gt_day.get("day")
        sub_day = _get_day(model_plan, day_idx)
        for slot in SLOTS:
            if slot not in gt_day and (gt_day.get(slot, "-") in (None, "", "-")):
                # 未声明的 slot 仍按官方用 "-" 比较
                pass
            expected = gt_day.get(slot, "-")
            actual = sub_day.get(slot, "-") if sub_day else "-"
            total += 1
            if slot_similarity(expected, actual) >= SIM_TH:
                matched += 1
    return matched / total if total else 0.0


def format_judge_answer(name: str, gt_plans: list[dict[str, Any]]) -> str:
    lines = [f"Possible answer for {name}:"]
    for day in gt_plans:
        day_idx = day.get("days") if day.get("days") is not None else day.get("day")
        lines.append(f"Day {day_idx}:")
        for slot in SLOTS:
            label = slot.replace("_", " ").title()
            lines.append(f"{label}: {day.get(slot, '-')}")
        lines.append("")
    return "\n".join(lines)


def format_judge_hint(name: str, model_plan: list[dict[str, Any]], gt_plans: list[dict[str, Any]]) -> str:
    lines = [f"Feedback for {name}:", "The following slots need correction:"]
    has_error = False
    for gt_day in gt_plans:
        day_idx = gt_day.get("days") if gt_day.get("days") is not None else gt_day.get("day")
        model_day = _get_day(model_plan, day_idx)
        for slot in SLOTS:
            expected = gt_day.get(slot, "-")
            actual = model_day.get(slot, "-") if model_day else "-"
            if slot_similarity(expected, actual) < HINT_SIM_TH:
                lines.append(f"- Day {day_idx}, {slot.replace('_', ' ').title()}")
                has_error = True
    if not has_error:
        lines.append("- None (all correct)")
    return "\n".join(lines)


def judge_round(
    pred: str,
    ground_truth: Any,
    *,
    name: str = "",
    judgement_mode: JudgementMode = "hint",
) -> dict[str, Any]:
    """对单回合打分，并按 judgement_mode 生成官方反馈文本。"""
    person_name, gt_plans = _as_daily_plans(ground_truth, name)
    model_plan = parse_person_plan(pred, person_name)
    # 解析不出官方 `=== Name's Plan ===` 结构 → 判败（不做 GT 反向兜底：
    # 旧 fallback 用"GT 值是否出现在输出里"反构造 plan 再自比相似度，
    # 自证循环会虚高 round_success）
    success = evaluate_slots(model_plan, gt_plans)
    judgement = ""
    if judgement_mode == "hint":
        judgement = format_judge_hint(person_name, model_plan, gt_plans)
    elif judgement_mode == "answer":
        judgement = format_judge_answer(person_name, gt_plans)
    return {
        "success": success,
        "slot_accuracy": slot_match_rate(model_plan, gt_plans),
        "judgement_mode": judgement_mode,
        "judgement": judgement,
        "name": person_name,
    }


class MemoryArenaTravelCalculator(MetricCalculator):
    """MemoryArena travel：round_success = 官方 slot 判定。"""

    name: ClassVar[str] = "memoryarena_travel"
    kind: ClassVar[MetricKind] = "benchmark"
    metrics: ClassVar[tuple[str, ...]] = ("round_success", "slot_accuracy")

    def __init__(self, judgement_mode: JudgementMode = "hint"):
        self.judgement_mode = judgement_mode

    def calculate(self, inp: MetricInput) -> MetricBundle:
        task = inp.task
        if task is None:
            return MetricBundle(name=self.name, kind=self.kind)
        data = task.data if isinstance(task.data, dict) else {}
        mode = inp.extra.get("judgement_mode") or data.get("judgement_mode") or self.judgement_mode
        if mode not in ("hint", "answer", "none"):
            mode = "hint"

        successes = 0
        slot_scores: list[float] = []
        details: list[dict[str, Any]] = []
        n = 0
        for idx, question, query, gt, pred in round_items(inp):
            n += 1
            outcome = outcome_for_round(inp, idx)
            evidence = outcome.environment if outcome else None
            managed = task.task_environment.get("type") == "memoryarena"
            if (managed and (evidence is None or evidence.reward is None)) or (
                outcome and not outcome.success
            ):
                details.append({"round_idx": idx, "score_status": "not_measured", "official_score": None})
                continue
            name = question.get("name", "") if isinstance(question, dict) else ""
            judged = judge_round(pred, gt, name=name, judgement_mode=mode)
            if evidence and evidence.env_name == "travel_planner" and evidence.reward is not None:
                judged["success"] = bool(evidence.reward)
            if judged["success"]:
                successes += 1
            slot_scores.append(float(judged["slot_accuracy"]))
            details.append(
                {
                    "round_idx": idx,
                    "query": query,
                    "success": judged["success"],
                    "slot_accuracy": judged["slot_accuracy"],
                    "judgement_mode": judged["judgement_mode"],
                    "judgement": judged["judgement"],
                    "score_status": "measured",
                    "official_score": float(judged["success"]),
                }
            )

        values = (
            {
                "round_success": successes / n if n else 0.0,
                "slot_accuracy": sum(slot_scores) / len(slot_scores) if slot_scores else 0.0,
            }
            if n and all(d["score_status"] == "measured" for d in details)
            else {}
        )
        return MetricBundle(
            name=self.name,
            kind=self.kind,
            values=values,
            details=details,
        )
