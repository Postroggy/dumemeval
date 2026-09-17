"""Utility 指标：任务表现（task_success / Δutility / turns / cost）。

task_success 语义（见 docs/metrics/utility-official-backfill.md）：
- benchmark 提供官方主指标时：official_score >= 0.5（任务结果）
- 否则回退：全部 session 完成（完成率）
"""

from __future__ import annotations

from typing import ClassVar

from ...models import SessionOutcome, UtilityResult
from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind


class UtilityEvaluator(MetricCalculator):
    """任务表现评测器。"""

    name: ClassVar[str] = "utility"
    kind: ClassVar[MetricKind] = "utility"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        outcomes = [o for o in inp.outcomes if isinstance(o, SessionOutcome)]
        official = inp.extra.get("official_task_score")
        official_score = float(official) if official is not None else None
        successes = [o for o in outcomes if o.success]
        ur = UtilityResult(
            task_success=(
                official_score >= 0.5
                if official_score is not None
                else bool(outcomes) and len(successes) == len(outcomes)
            ),
            success_rate=len(successes) / len(outcomes) if outcomes else 0.0,
            turns=len(outcomes),
            cost_usd=sum(getattr(o, "cost_usd", 0.0) for o in outcomes),
        )
        if official_score is not None:
            ur.details.append({"source": "benchmark_official", "score": official_score, "threshold": 0.5})
        baseline = inp.extra.get("baseline_success_rate")
        if baseline is not None:
            ur.memory_conditioned_gain = ur.success_rate - float(baseline)
        return MetricBundle(
            name=self.name,
            kind=self.kind,
            values={
                "task_success": 1.0 if ur.task_success else 0.0,
                "success_rate": ur.success_rate,
                "turns": float(ur.turns),
                "cost_usd": ur.cost_usd,
                "memory_conditioned_gain": ur.memory_conditioned_gain,
            },
            details=ur.details,
        )


UtilityCalculator = UtilityEvaluator
