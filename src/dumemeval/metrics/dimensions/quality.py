"""Quality 指标：Memory 本身的质量（precision / recall / hallucination / omission）。

实现从 quality/metrics.py 迁入统一 metrics 层；QualityProbe 仍留在 quality/。
"""

from __future__ import annotations

from typing import Any, ClassVar

from ...models import MemoryFact, QualityResult
from ...verifier import VerifierFactory
from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind


class QualityEvaluator(MetricCalculator):
    """Memory 质量评测器。"""

    name: ClassVar[str] = "quality"
    kind: ClassVar[MetricKind] = "quality"

    def __init__(self, verifier_config: dict[str, Any] | None = None):
        self.verifier = VerifierFactory.create(verifier_config or {"type": "llm_judge"})

    def calculate(self, inp: MetricInput) -> MetricBundle:
        qr = self.score_memory(inp.memory_files, inp.ground_truth_facts, probe_events=inp.probe_events)
        values: dict[str, float] = {
            "precision": qr.precision,
            "recall": qr.recall,
            "hallucination_rate": qr.hallucination_rate,
            "omission_rate": qr.omission_rate,
        }
        # update_accuracy 当前无实现（None = 未测），不写进 values——
        # 报告显示 n/a 而不是误导性的 0.0
        if qr.update_accuracy is not None:
            values["update_accuracy"] = qr.update_accuracy
        return MetricBundle(name=self.name, kind=self.kind, values=values, details=qr.details)

    def score_memory(
        self,
        memory_files: dict[str, str],
        ground_truth_facts: list[MemoryFact],
        probe_events: list[dict[str, Any]] | None = None,
    ) -> QualityResult:
        """Score memory contents against typed ground-truth facts."""
        qr = QualityResult()
        if not ground_truth_facts:
            return qr

        memory_text = "\n".join(memory_files.values())
        if probe_events:
            write_contents = [
                e.get("content", "")
                for e in probe_events
                if e.get("type") == "memory_write" and e.get("content")
            ]
            if write_contents:
                memory_text = "\n".join([memory_text, *write_contents])

        details: list[dict[str, Any]] = []
        matched = 0
        for fact in ground_truth_facts:
            verdict = self.verifier.verify(memory_text, fact.fact, category=fact.category)
            hit = verdict.is_pass
            if hit:
                matched += 1
            details.append(
                {
                    "fact": fact.fact,
                    "category": fact.category,
                    "in_memory": hit,
                    "score": verdict.score,
                    "reason": verdict.reason,
                    "label": verdict.label,
                    "runs": verdict.runs,
                    "score_std": _score_std(verdict.run_scores),
                }
            )

        total = len(ground_truth_facts)
        qr.recall = matched / total if total else 0.0
        if memory_files:
            relevant = 0
            for ftext in memory_files.values():
                if any(
                    self.verifier.verify(ftext, fact.fact, category=fact.category).is_pass
                    for fact in ground_truth_facts
                ):
                    relevant += 1
            qr.precision = relevant / len(memory_files)
        else:
            qr.precision = 0.0
        qr.hallucination_rate = 1.0 - qr.precision if memory_files else 0.0
        qr.omission_rate = 1.0 - qr.recall if total else 0.0
        qr.details = details
        return qr


def _score_std(scores: list[float]) -> float:
    """样本标准差；少于 2 次运行为 0。"""
    if len(scores) < 2:
        return 0.0
    mean = sum(scores) / len(scores)
    var = sum((s - mean) ** 2 for s in scores) / (len(scores) - 1)
    return float(var**0.5)


QualityCalculator = QualityEvaluator
