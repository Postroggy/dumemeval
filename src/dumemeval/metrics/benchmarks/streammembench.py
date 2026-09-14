"""StreamMemBench 官方指标（smoke/local 确定性路径）。

Canonical 名称（streammembench.evaluation.metrics.METRIC_NAMES）：
- fidelity
- initial_evidence_use
- feedback_incorporation
- followup_reuse

语义（docs/evaluation.md + runner.py + DeterministicUserFeedbackSimulator）：
- 每条 0/1；聚合为 [0,1] 均值
- fidelity：记忆记录与 evidence_statement 的 token overlap ≥ 0.5 → 1
- initial_evidence_use：首答 overlap(evidence)≥0.5 且 overlap(expected_behavior)≥0.3 → 1，否则 0
- 若首答已通过：feedback_incorporation 不计分母（applicable=false，值记 0）
- 若首答需修改：对 revised_answer 再跑同一判定 → feedback_incorporation
- followup_reuse：followup 答案通过同一判定 → 1

禁止把 expected_behavior / evidence_statement 当作「另一个数据集的 accuracy」。
token_overlap_score 来自官方 utils/text.py。
"""

from __future__ import annotations

import re
from typing import ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind, prediction_for_item

METRIC_NAMES = (
    "fidelity",
    "initial_evidence_use",
    "feedback_incorporation",
    "followup_reuse",
)

_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]")

_DET_FEEDBACK = {
    "zh": {
        "affirm_type": "肯定",
        "revise_type": "需要修改",
        "revise_feedback": "这里需要补充一个关键信息：{evidence} 请基于这一点重新回答我的问题。",
    },
    "en": {
        "affirm_type": "affirm",
        "revise_type": "revise",
        "revise_feedback": (
            "A key piece of information needs to be added: {evidence} Please re-answer my question based on this."
        ),
    },
}


def tokenize_lower(text: str) -> set[str]:
    """官方 utils/text.py tokenize_lower。"""
    return {match.group(0).lower() for match in _WORD_RE.finditer(text)}


def token_overlap_score(query: str, text: str) -> float:
    """官方 token_overlap_score：|query ∩ text| / |query|。"""
    query_tokens = tokenize_lower(query)
    if not query_tokens:
        return 0.0
    text_tokens = tokenize_lower(text)
    return len(query_tokens & text_tokens) / len(query_tokens)


def evidence_use_score(answer: str, evidence_statement: str) -> float:
    """官方 metrics.evidence_use_score。"""
    return max(0.0, min(1.0, token_overlap_score(evidence_statement, answer)))


def expected_behavior_score(answer: str, expected_behavior: str) -> float:
    """官方 metrics.expected_behavior_score。"""
    return max(0.0, min(1.0, token_overlap_score(expected_behavior, answer)))


def initial_passes(answer: str, evidence_statement: str, expected_behavior: str) -> bool:
    """官方 DeterministicUserFeedbackSimulator：≥0.5 且 ≥0.3 则肯定。"""
    return (
        evidence_use_score(answer, evidence_statement) >= 0.5
        and expected_behavior_score(answer, expected_behavior) >= 0.3
    )


class StreamMemBenchCalculator(MetricCalculator):
    """StreamMemBench：官方四指标（确定性 smoke 路径）。"""

    name: ClassVar[str] = "streammembench"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, lang: str = "zh"):
        self.lang = lang if lang in _DET_FEEDBACK else "en"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        task = inp.task
        data = task.data if task is not None and isinstance(task.data, dict) else {}
        evidence = str(data.get("evidence_statement") or "")
        initial_req = str(data.get("initial_user_request") or "")
        followup_req = str(data.get("followup_user_request") or "")
        initial_expected = str(data.get("initial_expected_behavior") or "")
        followup_expected = str(data.get("followup_expected_behavior") or "")

        initial_answer = prediction_for_item(inp.outputs, initial_req, 0)
        followup_answer = prediction_for_item(inp.outputs, followup_req, 1)
        # revise:: 前缀是 revision 轮的专用键，只能按精确 query 匹配（无下标兜底）
        revised_answer = next(
            (item.output for item in inp.outputs if item.query == f"revise::{initial_req}"), ""
        )

        memory_text = "\n".join(inp.memory_files.values()) if inp.memory_files else ""
        fidelity_overlap = token_overlap_score(evidence, memory_text) if evidence else 0.0
        fidelity = 1.0 if fidelity_overlap >= 0.5 else 0.0

        passed_initial = initial_passes(initial_answer, evidence, initial_expected)
        initial_evidence_use = 1.0 if passed_initial else 0.0
        applicable = not passed_initial
        if applicable:
            feedback_incorporation = (
                1.0 if initial_passes(revised_answer, evidence, initial_expected) else 0.0
            )
        else:
            feedback_incorporation = 0.0

        followup_reuse = 1.0 if initial_passes(followup_answer, evidence, followup_expected) else 0.0

        values = {
            "fidelity": fidelity,
            "initial_evidence_use": initial_evidence_use,
            "feedback_incorporation": feedback_incorporation,
            "followup_reuse": followup_reuse,
            "feedback_incorporation_applicable": 1.0 if applicable else 0.0,
        }
        details = [
            {
                "evidence_id": data.get("evidence_id"),
                "fidelity_overlap": fidelity_overlap,
                "initial_evidence_use": initial_evidence_use,
                "feedback_incorporation_applicable": applicable,
                "feedback_incorporation": feedback_incorporation,
                "followup_reuse": followup_reuse,
            }
        ]
        return MetricBundle(name=self.name, kind=self.kind, values=values, details=details)
