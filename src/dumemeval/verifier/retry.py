"""Judge aggregation and retries limited to explicit rate-limit rejection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from ..core.retry import call_with_retries as _call_with_retries
from .base import Verdict

__all__ = ["aggregate_verdicts", "call_with_retries", "is_retryable"]


def is_retryable(exc: BaseException) -> bool:
    """A received 429 rejects inference; timeout/connection/5xx delivery is uncertain."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return bool(status == 429)


def call_with_retries[T](
    fn: Callable[[], T],
    max_retries: int = 3,
    sleep_fn: Callable[[float], None] | None = None,
    base_delay: float = 0.5,
) -> T:
    """Apply the judge's delivery policy using the shared bounded retry loop."""
    return _call_with_retries(fn, max_retries, sleep_fn, base_delay, retry_if=is_retryable)


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
        run_raws=[item.raw for item in verdicts],
    )
