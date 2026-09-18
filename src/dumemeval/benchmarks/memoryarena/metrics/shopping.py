"""MemoryArena bundled_shopping 官方指标。

来源：
- run_shopping.py 默认 split_steps=true：每个商品使用独立的单步任务环境。
- summary_build.py ``hydrate_step_summary``：本步购买 ASIN 与本步目标匹配；
  ``enrich_task_result`` 的 overall_success 要求每步 match_ground_truth 均为真。
- webshop_env.py ``_build_judgement``：单步环境购买列表与该步目标列表完全相等。

本计算器仅使用 host 采集的 environment evidence；提及 ASIN 不代表购买。
商品属性与 compute_reward.py 的 fallback reward 未覆盖；没有购买商品属性证据时不计算。
不把 travel 的 slot / round_success 套到购物任务上。
"""

from __future__ import annotations

from typing import Any, ClassVar

from dumemeval.metrics.core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind


def normalize_expected_asins(ground_truth: Any) -> list[str]:
    """官方 webshop_env._normalize_expected_asins。"""
    raw: Any = ground_truth
    if isinstance(ground_truth, dict):
        if "target_asins" in ground_truth:
            raw = ground_truth["target_asins"]
        elif "target_products" in ground_truth:
            raw = ground_truth["target_products"]
        elif "target_asin" in ground_truth:
            raw = [ground_truth["target_asin"]]
        else:
            raw = []
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list):
        return [str(item).upper() for item in raw if item]
    return []


class MemoryArenaShoppingCalculator(MetricCalculator):
    """Score each product episode; legacy cumulative evidence requires aligned deltas."""

    name: ClassVar[str] = "memoryarena_shopping"
    kind: ClassVar[MetricKind] = "benchmark"
    metrics: ClassVar[tuple[str, ...]] = ("match_ground_truth", "overall_success")

    def calculate(self, inp: MetricInput) -> MetricBundle:
        if inp.task is None:
            return MetricBundle(name=self.name, kind=self.kind)
        details: list[dict[str, Any]] = []
        answers = inp.task.data.get("answers", [])
        sessions = [session for session in inp.task.sessions if session.query is not None]
        outcomes = {outcome.session_id: outcome for outcome in inp.outcomes}
        previous: dict[str, list[str]] = {}
        flags: list[float] = []
        for idx, session in enumerate(sessions):
            gold = answers[idx] if idx < len(answers) else None
            round_expected = normalize_expected_asins(gold)
            outcome = outcomes.get(session.id)
            evidence = outcome.environment if outcome else None
            detail: dict[str, Any] = {
                "round_idx": idx,
                "query": session.query,
                "session_id": session.id,
                "execution_status": "completed" if outcome and outcome.success else "not_completed",
                "score_status": "not_measured",
                "official_score": None,
                "attribute_score_status": "not_measured",
                "attribute_score_reason": "Purchased product attributes are not captured.",
            }
            if evidence and evidence.env_name == "webshop" and outcome and outcome.success and round_expected:
                purchases = evidence.info.get("purchased_asins")
                observed_purchases = evidence.observation.get("purchases")
                if purchases is None and isinstance(observed_purchases, list):
                    purchases = [
                        purchase.get("asin") for purchase in observed_purchases if isinstance(purchase, dict)
                    ]
                if isinstance(purchases, list) and all(isinstance(asin, str) for asin in purchases):
                    purchased = [str(asin).upper() for asin in purchases]
                    if evidence.info.get("episode_scope") == "session":
                        round_purchases = purchased
                    else:
                        before = previous.get(evidence.task_id, [] if idx == 0 else None)
                        previous[evidence.task_id] = purchased
                        if before is None or purchased[: len(before)] != before:
                            detail["reason"] = "Cumulative purchases cannot be aligned to this round."
                            details.append(detail)
                            continue
                        round_purchases = purchased[len(before) :]
                    correct = round_purchases == round_expected
                    flags.append(float(correct))
                    detail.update(
                        score_status="measured",
                        official_score=float(correct),
                        match_ground_truth=correct,
                        purchased_asins=purchased,
                        round_purchased_asins=round_purchases,
                        expected_asins=round_expected,
                        episode_scope=evidence.info.get("episode_scope", "legacy_cumulative"),
                        environment_task_id=evidence.task_id,
                    )
            details.append(detail)

        values: dict[str, float] = {}
        if sessions and len(flags) == len(sessions):
            values["match_ground_truth"] = sum(flags) / len(flags)
            # A truncated sample is not a completed official bundle.
            if len(sessions) == inp.task.data.get("source_round_count", len(sessions)):
                values["overall_success"] = float(all(flags))
        return MetricBundle(
            name=self.name,
            kind=self.kind,
            values=values,
            details=details,
        )
