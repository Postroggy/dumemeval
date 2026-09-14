"""Judge 多次运行聚合；瞬时重试再导出 core.retry。"""

from __future__ import annotations

from collections import Counter

from ..core.retry import call_with_retries, is_retryable
from .base import Verdict

__all__ = ["aggregate_verdicts", "call_with_retries", "is_retryable"]


def aggregate_verdicts(verdicts: list[Verdict]) -> Verdict:
    """多次运行：多数 label + 分数均值。"""
    if not verdicts:
        raise ValueError("aggregate_verdicts requires at least one verdict")
    scores = [item.score for item in verdicts]
    labels = [item.label for item in verdicts]
    label = Counter(labels).most_common(1)[0][0]
    reason = next(item.reason for item in verdicts if item.label == label)
    return Verdict(
        label=label,
        score=sum(scores) / len(scores),
        reason=reason,
        raw=verdicts[-1].raw,
        runs=len(verdicts),
        run_scores=scores,
    )
