"""MemoryArena bundled_shopping 官方指标。

来源：
- env/env_systems/webshop_env.py ``_build_judgement``：
  ``match_ground_truth`` = 购买 ASIN 列表与 expected ASIN 列表完全相等
- run_shopping.py：``overall_success`` = 每步 match_ground_truth 均为真
- web_shopping_env/compute_reward.py：ASIN 精确匹配时 reward=1.0；
  否则 ``compute_attribute_matches``（--no-llm 字符串子串，normalize_for_match）

本计算器在 AgentOutput 文本上抽取 ASIN，再套上述官方判定。
不把 travel 的 slot / round_success 套到购物任务上。
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from ..core.base import (
    MetricBundle,
    MetricCalculator,
    MetricInput,
    MetricKind,
    round_items,
)

# Amazon ASIN：样本如 B00TUDFEW2 / B08957C9ZH
_ASIN_RE = re.compile(r"\b(B0[0-9A-Z]{8})\b", re.IGNORECASE)


def normalize_for_match(text: str) -> str:
    """官方 reward_helpers.normalize_for_match。"""
    text = text.lower()
    text = re.sub(r"[-/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_attribute_matches(
    attributes: list[str], purchased_name: str | None
) -> tuple[int, list[str], list[str]]:
    """官方 reward_helpers.compute_attribute_matches（字符串路径 / --no-llm）。"""
    if not attributes:
        return 0, [], []
    normalized_name = normalize_for_match(purchased_name or "")
    matched: list[str] = []
    missing: list[str] = []
    for attr in attributes:
        normalized_attr = normalize_for_match(attr)
        if normalized_attr and normalized_attr in normalized_name:
            matched.append(attr)
        else:
            missing.append(attr)
    return len(matched), matched, missing


def extract_asins(text: str) -> list[str]:
    """从 agent 输出抽取 ASIN，顺序保留（对应 purchased_asins 序列）。"""
    return [match.group(1).upper() for match in _ASIN_RE.finditer(text or "")]


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


def score_shopping_round(pred: str, ground_truth: Any) -> dict[str, Any]:
    """单回合：官方 exact ASIN match + 官方 attribute 字符串匹配。"""
    expected = normalize_expected_asins(ground_truth)
    attributes: list[str] = []
    if isinstance(ground_truth, dict):
        attrs = ground_truth.get("attributes") or []
        attributes = [str(a) for a in attrs] if isinstance(attrs, list) else []
    target = expected[0] if expected else ""
    purchased = extract_asins(pred)
    exact = bool(expected) and purchased == expected
    n_matched, matched, missing = compute_attribute_matches(attributes, pred)
    r_attr = (n_matched / len(attributes)) if attributes else 0.0
    reward = 1.0 if exact else r_attr
    return {
        "match_ground_truth": exact,
        "target_asin": target,
        "purchased_asins": purchased,
        "attribute_match": r_attr,
        "matched_attributes": matched,
        "missing_attributes": missing,
        "reward": reward,
    }


class MemoryArenaShoppingCalculator(MetricCalculator):
    """bundled_shopping：match_ground_truth / overall_success / attribute_match。"""

    name: ClassVar[str] = "memoryarena_shopping"
    kind: ClassVar[MetricKind] = "benchmark"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        details: list[dict[str, Any]] = []
        exact_flags: list[float] = []
        attr_scores: list[float] = []
        n = 0
        for idx, _question, query, gold, pred in round_items(inp):
            n += 1
            scored = score_shopping_round(pred, gold)
            exact_flags.append(1.0 if scored["match_ground_truth"] else 0.0)
            attr_scores.append(float(scored["attribute_match"]))
            details.append({"round_idx": idx, "query": query, **scored})

        overall = 1.0 if exact_flags and all(flag == 1.0 for flag in exact_flags) else 0.0
        return MetricBundle(
            name=self.name,
            kind=self.kind,
            values={
                "match_ground_truth": sum(exact_flags) / n if n else 0.0,
                "overall_success": overall,
                "attribute_match": sum(attr_scores) / len(attr_scores) if attr_scores else 0.0,
            },
            details=details,
        )
