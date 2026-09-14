"""Locomo-Plus 官方指标（6 类 LLM-as-judge）。

来源：benchmarks/conversation/Locomo-Plus/evaluation_framework/task_eval/：
- ``llm_as_judge.py``：LABEL_TO_SCORE = {correct: 1.0, partial: 0.5, wrong: 0.0}
  （L28-30），未知 label 计 0；Cognitive 类无 gold（L33-35）
- ``prompt.py``：6 类 judge 模板（multi-hop/single-hop/temporal/common-sense/
  adversarial/Cognitive + default），全部要求输出 JSON {"label": ...}
- Cognitive 类判定"prediction 是否体现/关联 evidence"（cue_dialogue），二分类

注意：Locomo-Plus 不复用 LoCoMo 的 F1/EM——是纯 LLM judge 评分。
本实现把 6 类模板内嵌，judge 输出解析为 correct/partial/wrong → 分数。
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from .locomo import JudgeFn

LABEL_TO_SCORE = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}

# 官方 prompt.py 的 6 类模板（逐字移植，default 兜底）
_PROMPT_TEMPLATES: dict[str, str] = {
    "multi-hop": """You are a Fact-Checking Judge.
Your task: Compare the model's prediction with the reference answer (multi-hop fact QA).

Labels:
- "correct": The answer matches the reference entities (names, places, times) exactly.
- "partial": The answer misses some details or contains minor inaccuracies but gets the main entity right.
- "wrong": The answer is factually incorrect or hallucinates details not in the reference.

Reference Answer:
{gold}

Model Prediction:
{pred}

Relevant Evidence:
{evidence}

Return your judgment strictly in JSON format:
{{"label": "correct"|"partial"|"wrong", "reason": "<short explanation>"}}""",
    "single-hop": """You are a Fact-Checking Judge.
Your task: Compare the model's prediction with the reference answer (single-hop fact QA).

Labels:
- "correct": The answer matches the reference entities exactly.
- "partial": The answer misses some details but gets the main entity right.
- "wrong": The answer is factually incorrect or hallucinates details not in the reference.

Reference Answer:
{gold}

Model Prediction:
{pred}

Relevant Evidence:
{evidence}

Return your judgment strictly in JSON format:
{{"label": "correct"|"partial"|"wrong", "reason": "<short explanation>"}}""",
    "temporal": """You are a Temporal Logic Judge.
Your task: Check the calculation, duration, or sequence of events in the model prediction against the reference answer.

Labels:
- "correct": The temporal facts (dates, durations, ordering) match the reference.
- "partial": Mostly correct but with minor temporal inaccuracies.
- "wrong": The temporal information is incorrect.

Reference Answer:
{gold}

Model Prediction:
{pred}

Relevant Evidence:
{evidence}

Return your judgment strictly in JSON format:
{{"label": "correct"|"partial"|"wrong", "reason": "<short explanation>"}}""",
    "common-sense": """You are a Common-Sense Judge.
Your task: Judge whether the model prediction is consistent with the reference answer using common sense.

Labels:
- "correct": The prediction is consistent with common sense and the reference.
- "partial": Partially consistent.
- "wrong": Inconsistent or nonsensical.

Reference Answer:
{gold}

Model Prediction:
{pred}

Relevant Evidence:
{evidence}

Return your judgment strictly in JSON format:
{{"label": "correct"|"partial"|"wrong", "reason": "<short explanation>"}}""",
    "adversarial": """You are an Adversarial Robustness Judge.
Your task: Determine whether the model correctly refuses to answer or handles the unanswerable question appropriately.

Labels:
- "correct": The prediction appropriately refuses or handles the unanswerable question.
- "partial": Partially appropriate.
- "wrong": The prediction fabricates an answer or fails to handle appropriately.

Reference Answer:
{gold}

Model Prediction:
{pred}

Relevant Evidence:
{evidence}

Return your judgment strictly in JSON format:
{{"label": "correct"|"wrong", "reason": "<short explanation>"}}""",
    "Cognitive": """You are a Memory Awareness Judge.
Your task: Judge whether the Model Prediction considers or is linked to the Evidence. If there is a clear connection, the answer is correct (score 1); if not, it is wrong (no score).

Labels:
- "correct": The prediction explicitly or implicitly reflects/uses the evidence (memory or constraint). Give 1 point.
- "wrong": The prediction does not show such a link to the evidence. No point.

Memory/Evidence:
{evidence}

Model Prediction:
{pred}

Return your judgment strictly in JSON format:
{{"label": "correct"|"wrong", "reason": "<Does the prediction relate to the evidence?>"}}""",
    "default": """You are an expert evaluator.
Your task: Compare the prediction with the reference.

Labels:
- "correct": Factually consistent with the reference.
- "partial": Contains correct info but is incomplete.
- "wrong": Factually incorrect.

Reference Answer:
{gold}

Model Prediction:
{pred}

Relevant Evidence:
{evidence}

Return your judgment strictly in JSON format:
{{"label": "correct"|"partial"|"wrong", "reason": "<short explanation>"}}""",
}

# 6 类 + 默认（用于分桶）
CATEGORIES = (
    "multi-hop",
    "single-hop",
    "temporal",
    "common-sense",
    "adversarial",
    "Cognitive",
)


def build_judge_prompt(category: str, evidence: str, pred: str, gold: str = "") -> str:
    """官方 get_judge_prompt：取模板填 gold/pred/evidence。"""
    template = _PROMPT_TEMPLATES.get(category) or _PROMPT_TEMPLATES["default"]
    return template.format(gold=gold or "", pred=pred or "", evidence=evidence or "")


def parse_judge_label(raw: str) -> str:
    """官方 _parse_judge_response：优先 JSON 的 label，fallback 关键词。"""
    if not raw:
        return ""
    cleaned = raw.strip()
    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            label = str(data.get("label", "")).strip().lower()
            if label in LABEL_TO_SCORE:
                return label
        except (json.JSONDecodeError, ValueError):
            pass
    lowered = cleaned.lower()
    if "correct" in lowered:
        return "correct"
    if "partial" in lowered:
        return "partial"
    if "wrong" in lowered:
        return "wrong"
    return ""


def label_to_score(label: str) -> float:
    """官方 label_to_score。"""
    return LABEL_TO_SCORE.get((label or "").strip().lower(), 0.0)


class LocomoPlusCalculator(MetricCalculator):
    """Locomo-Plus：6 类 LLM judge 评分（correct=1/partial=0.5/wrong=0）。"""

    name: ClassVar[str] = "locomo_plus"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        samples = data.get("samples") or []
        by_cat: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        n = 0
        for idx, sample in enumerate(samples):
            if not isinstance(sample, dict):
                continue
            n += 1
            query = str(sample.get("trigger_query") or "")
            category = str(sample.get("category") or "default")
            gold = str(sample.get("answer") or "")
            evidence = str(sample.get("cue_dialogue") or "")
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output
            label = self._judge_one(pred, gold, query, evidence, category)
            score = label_to_score(label)
            by_cat.setdefault(category, []).append(score)
            details.append(
                {
                    "idx": idx,
                    "category": category,
                    "label": label,
                    "score": score,
                    "predicted": pred[:200],
                }
            )

        values: dict[str, float] = {"score": sum(v for vs in by_cat.values() for v in vs) / n if n else 0.0}
        by_category: dict[str, dict[str, float]] = {}
        for cat, scores in by_cat.items():
            by_category[cat] = {
                "score": sum(scores) / len(scores) if scores else 0.0,
                "count": float(len(scores)),
            }
            values[f"score_{cat}"] = by_category[cat]["score"]
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )

    def _judge_one(self, pred: str, gold: str, query: str, evidence: str, category: str) -> str:
        if not pred:
            return ""
        if self._judge is not None:
            # 注入 judge 支持 partial：bool → 1.0/0.0，float（0.0~1.0）直接作分
            raw = self._judge(pred, gold, query)
            if isinstance(raw, bool):
                return "correct" if raw else "wrong"
            return "partial" if 0.0 < float(raw) < 1.0 else ("correct" if float(raw) >= 1.0 else "wrong")
        if self._llm is None:
            from ...verifier import make_llm_judge

            self._llm = make_llm_judge("task_success", self._llm_config)
        # 用官方 6 类模板走真实 LLM（verify_with_prompt 暴露原始 prompt 入口）
        prompt = build_judge_prompt(category, evidence, pred, gold)
        verdict = self._llm.verify_with_prompt(prompt)
        return parse_judge_label(verdict.raw)
