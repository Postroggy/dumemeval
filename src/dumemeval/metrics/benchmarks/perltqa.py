"""PerLTQA 官方指标（⚠️ 官方评测代码未随仓库发布，采用确定性判分）。

数据：Dataset/benchmarks/conversation/PerLTQA/Dataset/{en,zh}/perltqa_*.json
官方只发布数据（论文指标：classification/retrieval/synthesis），无评测代码。

本实现采用与 LoCoMo 同款的确定性判分（normalize + token F1 + EM）作为替代，
并在报告注明这是适配层自定义判分、非官方口径。如需官方判分需实现论文的
LLM judge（分类/检索/合成三阶段）。
"""

from __future__ import annotations

import re
import string
from collections import Counter
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind


def normalize_answer(text: str) -> str:
    """与 LoCoMo 同款的 normalize（去标点/大小写/冠词）。"""
    text = (text or "").lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\b(a|an|the|and)\b", " ", text)
    return " ".join(text.split())


def token_f1(prediction: str, gold: str) -> float:
    pred_tokens = Counter(normalize_answer(prediction).split())
    gold_tokens = Counter(normalize_answer(gold).split())
    common = pred_tokens & gold_tokens
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(list(pred_tokens.elements())) if pred_tokens else 0.0
    recall = num_same / len(list(gold_tokens.elements())) if gold_tokens else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def exact_match(prediction: str, gold: str) -> bool:
    return normalize_answer(prediction) == normalize_answer(gold)


class PerLTQACalculator(MetricCalculator):
    """PerLTQA：EM + token F1（适配层判分，非官方）。"""

    name: ClassVar[str] = "perltqa"
    kind: ClassVar[MetricKind] = "benchmark"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        questions = data.get("questions") or []
        em_flags: list[float] = []
        f1_scores: list[float] = []
        by_section: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        n = 0
        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            n += 1
            query = str(q.get("question") or "")
            answer = str(q.get("answer") or "")
            section = str(q.get("section") or "unknown")
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output
            f1 = token_f1(pred, answer)
            em = 1.0 if exact_match(pred, answer) else 0.0
            em_flags.append(em)
            f1_scores.append(f1)
            by_section.setdefault(section, []).append(f1)
            details.append(
                {
                    "idx": idx,
                    "section": section,
                    "em": em,
                    "f1": f1,
                    "predicted": pred[:200],
                }
            )

        values: dict[str, float] = {
            "em": sum(em_flags) / n if n else 0.0,
            "f1": sum(f1_scores) / n if n else 0.0,
        }
        by_category: dict[str, dict[str, float]] = {}
        for section, scores in by_section.items():
            by_category[section] = {
                "f1": sum(scores) / len(scores) if scores else 0.0,
                "count": float(len(scores)),
            }
            values[f"f1_{section}"] = by_category[section]["f1"]
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )
