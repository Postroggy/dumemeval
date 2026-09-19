"""MemoryArena bundled_shopping 官方指标。

来源：
- run_shopping.py 默认 split_steps=true：每个商品使用独立的单步任务环境。
- summary_build.py ``hydrate_step_summary``：本步购买 ASIN 与本步目标匹配；
  ``enrich_task_result`` 的 overall_success 要求每步 match_ground_truth 均为真。
- webshop_env.py ``_build_judgement``：单步环境购买列表与该步目标列表完全相等。

本计算器仅使用 host 采集的 environment evidence；提及 ASIN 不代表购买。
受管环境调用固定上游 compute_reward.py，报告完整 reward 与可选 LLM attribute judge；
缺少完整 reward 证据时，商品属性仅按 reward_helpers.py 的字符串回退规则计算。
不把 travel 的 slot / round_success 套到购物任务上。
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from dumemeval.metrics.core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from dumemeval.models import BenchmarkResult


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


def score_attributes(
    attributes: list[str], purchased_name: str | None
) -> tuple[float | None, list[str], list[str]]:
    """Pinned reward_helpers.compute_attribute_matches string fallback."""
    if not attributes:
        return None, [], []

    def normalize(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[-/]", " ", value.lower())).strip()

    name = normalize(purchased_name or "")
    matched = [attr for attr in attributes if normalize(attr) and normalize(attr) in name]
    missing = [attr for attr in attributes if attr not in matched]
    return len(matched) / len(attributes), matched, missing


class MemoryArenaShoppingCalculator(MetricCalculator):
    """Score each product episode; legacy cumulative evidence requires aligned deltas."""

    name: ClassVar[str] = "memoryarena_shopping"
    kind: ClassVar[MetricKind] = "benchmark"
    metrics: ClassVar[tuple[str, ...]] = (
        "match_ground_truth",
        "overall_success",
        "attribute_match_ratio",
        "average_reward",
        "reward_item_success",
    )

    def calculate(self, inp: MetricInput) -> MetricBundle:
        if inp.task is None:
            return MetricBundle(name=self.name, kind=self.kind)
        details: list[dict[str, Any]] = []
        answers = inp.task.data.get("answers", [])
        sessions = [session for session in inp.task.sessions if session.query is not None]
        outcomes = {outcome.session_id: outcome for outcome in inp.outcomes}
        previous: dict[str, list[str]] = {}
        flags: list[float] = []
        attribute_ratios: list[float] = []
        attribute_rounds = 0
        reward_values: list[float] = []
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
                "attribute_score_reason": "Purchased product name is unavailable.",
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
                    official_reward = evidence.info.get("official_reward")
                    reward_entry: dict[str, Any] | None = (
                        official_reward if isinstance(official_reward, dict) else None
                    )
                    raw_components = reward_entry.get("components") if reward_entry else None
                    components: dict[str, Any] | None = (
                        raw_components if isinstance(raw_components, dict) else None
                    )
                    reward = reward_entry.get("reward") if reward_entry else None
                    if isinstance(reward, (int, float)) and isinstance(components, dict):
                        reward_values.append(float(reward))
                        detail.update(
                            reward=float(reward),
                            reward_success=bool(reward_entry.get("success")) if reward_entry else False,
                            reward_components=components,
                            reward_calculation=reward_entry.get("calculation") if reward_entry else None,
                            attribute_mode=evidence.info.get("attribute_mode"),
                            attribute_fallback_reason=evidence.info.get("attribute_fallback_reason"),
                        )
                    attributes_raw = gold.get("attributes") if isinstance(gold, dict) else None
                    if attributes_raw is None and isinstance(gold, dict):
                        requirements = gold.get("requirements")
                        attributes_raw = (
                            requirements.get("attributes") if isinstance(requirements, dict) else None
                        )
                    if isinstance(attributes_raw, list) and all(
                        isinstance(attr, str) for attr in attributes_raw
                    ):
                        if attributes_raw:
                            attribute_rounds += 1
                            official_ratio = components.get("attr_match_ratio") if components else None
                            if isinstance(official_ratio, (int, float)) and components is not None:
                                ratio = float(official_ratio)
                                matched = components.get("matched_attributes", [])
                                missing = components.get("missing_attributes", [])
                                purchased_name = reward_entry.get("purchased_name") if reward_entry else None
                                attribute_ratios.append(ratio)
                                detail.update(
                                    attribute_score_status="measured",
                                    attribute_score_reason="",
                                    attribute_match_ratio=ratio,
                                    matched_attributes=matched,
                                    missing_attributes=missing,
                                    purchased_name=purchased_name,
                                )
                            else:
                                products = evidence.info.get("purchased_products")
                                name: str | None = None
                                if not round_purchases:
                                    name = ""
                                elif isinstance(products, list):
                                    product = next(
                                        (
                                            item
                                            for item in products
                                            if isinstance(item, dict)
                                            and str(item.get("asin", "")).upper() == round_purchases[-1]
                                        ),
                                        None,
                                    )
                                    if isinstance(product, dict) and not evidence.info.get(
                                        "attribute_lookup_error"
                                    ):
                                        product_name = product.get("name")
                                        if product_name is None or isinstance(product_name, str):
                                            name = product_name or ""
                                if name is not None:
                                    fallback_ratio, matched, missing = score_attributes(attributes_raw, name)
                                    assert fallback_ratio is not None
                                    attribute_ratios.append(fallback_ratio)
                                    detail.update(
                                        attribute_score_status="measured",
                                        attribute_score_reason="",
                                        attribute_match_ratio=fallback_ratio,
                                        matched_attributes=matched,
                                        missing_attributes=missing,
                                        purchased_name=name,
                                    )
                        else:
                            detail["attribute_score_reason"] = "No attribute constraints in this step."
            details.append(detail)

        values: dict[str, float] = {}
        if sessions and len(flags) == len(sessions):
            values["match_ground_truth"] = sum(flags) / len(flags)
            # A truncated sample is not a completed official bundle.
            if len(sessions) == inp.task.data.get("source_round_count", len(sessions)):
                values["overall_success"] = float(all(flags))
            if attribute_rounds and len(attribute_ratios) == attribute_rounds:
                values["attribute_match_ratio"] = sum(attribute_ratios) / attribute_rounds
            if len(reward_values) == len(sessions):
                values["average_reward"] = sum(reward_values) / len(reward_values)
                if len(sessions) == inp.task.data.get("source_round_count", len(sessions)):
                    values["reward_item_success"] = float(all(score == 1.0 for score in reward_values))
        return MetricBundle(
            name=self.name,
            kind=self.kind,
            values=values,
            details=details,
        )

    def aggregate(self, results: list[BenchmarkResult]) -> BenchmarkResult | None:
        """Match upstream step-weighted reward and item-weighted success denominators."""
        if not results:
            return None
        details = [detail for result in results for detail in result.details]
        pooled = BenchmarkResult(
            benchmark=self.name,
            score_scope=results[0].score_scope,
            primary_metric="match_ground_truth",
            details=details,
        )
        if any("match_ground_truth" not in result.values for result in results):
            return pooled
        scored = [detail for detail in details if detail.get("score_status") == "measured"]
        if scored:
            pooled.values["match_ground_truth"] = sum(
                bool(detail["match_ground_truth"]) for detail in scored
            ) / len(scored)
        if all("overall_success" in result.values for result in results):
            pooled.values["overall_success"] = sum(
                result.values["overall_success"] for result in results
            ) / len(results)
        if all("attribute_match_ratio" in result.values for result in results):
            attribute_details = [
                detail for detail in details if detail.get("attribute_score_status") == "measured"
            ]
            if attribute_details:
                pooled.values["attribute_match_ratio"] = sum(
                    float(detail["attribute_match_ratio"]) for detail in attribute_details
                ) / len(attribute_details)
        if (
            scored
            and all("average_reward" in result.values for result in results)
            and all("reward" in detail for detail in scored)
        ):
            pooled.values["average_reward"] = sum(float(detail["reward"]) for detail in scored) / len(scored)
            if all("reward_item_success" in result.values for result in results):
                pooled.values["reward_item_success"] = sum(
                    result.values["reward_item_success"] for result in results
                ) / len(results)
        return pooled
