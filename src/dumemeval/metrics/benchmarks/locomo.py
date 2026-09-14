"""LoCoMo 官方指标：normalize + Porter stemmer 的 token F1 + 类别 accuracy。

F1 对齐 snap-research/locomo（Harbor adapters/locomo verifier 的镜像）：
- normalize：去逗号/标点/大小写，去掉 a/an/the/and
- tokens：Porter stem
- F1：Counter 多重集合重叠（不是 set）
- category 1 → 逗号分隔的 multi-F1；category 3 → 只取分号前半段；category 5 → 拒答

Accuracy 口径来源 OmniMemEval locomo_metric.py：按 category_mapping 分桶
（multi hop / temporal reasoning / open domain / single hop）。
"""

from __future__ import annotations

import re
import string
from collections import Counter
from collections.abc import Callable
from typing import Any, ClassVar

from nltk.stem.porter import PorterStemmer

from ...models import EvalTask
from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind, prediction_for_item

# OmniMemEval locomo_metric.py / GitHub Issue #6：JSON category ID ≠ 论文叙述顺序
CATEGORY_MAPPING: dict[int, str] = {
    1: "multi_hop",
    2: "temporal_reasoning",
    3: "open_domain",
    4: "single_hop",
    5: "adversarial",
}

REFUSAL_PHRASES = (
    "no information available",
    "not mentioned",
    "no record",
    "not recorded",
    "no such record",
    "cannot recall",
    "don't remember",
    "do not remember",
    "无此记录",
    "没有记录",
    "未记录",
)

_STEMMER = PorterStemmer()

JudgeFn = Callable[[str, str, str], float]


def normalize_answer(text: str) -> str:
    """官方 LoCoMo normalize_answer。"""
    text = text.replace(",", "")
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\b(a|an|the|and)\b", " ", text)
    return " ".join(text.split())


def _tokens(text: str) -> list[str]:
    return [_STEMMER.stem(word) for word in normalize_answer(text).split()]


def locomo_f1(prediction: str, gold: str) -> float:
    """单答案 token F1（Porter stem + Counter 重叠）。"""
    pred_tokens = _tokens(prediction)
    gold_tokens = _tokens(gold)
    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def locomo_f1_multi(prediction: str, gold: str) -> float:
    """category=1：逗号分隔的多答案 F1（每个 gold 取与 pred 片段的最大 F1 再平均）。"""
    preds = [part.strip() for part in prediction.split(",") if part.strip()]
    golds = [part.strip() for part in gold.split(",") if part.strip()]
    if not golds:
        return 0.0
    if not preds:
        return 0.0
    scores = [max(locomo_f1(pred, gold_part) for pred in preds) for gold_part in golds]
    return sum(scores) / len(scores)


def _contains_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in REFUSAL_PHRASES)


def _resolve_cat5_answer(predicted: str, option_a: str, option_b: str) -> str:
    pred = predicted.strip().lower()
    if len(pred) == 1:
        return option_a if "a" in pred else option_b
    if len(pred) == 3:
        return option_a if "(a)" in pred else option_b
    return predicted


def _latin_spans(text: str) -> str:
    """抽出拉丁/数字片段，避免中英混排把 gold 英文粘在 CJK 词里（官方 normalize 不去括号）。"""
    spans = re.findall(r"[A-Za-z0-9][A-Za-z0-9']*", text)
    return " ".join(spans)


def score_locomo_f1(
    prediction: str, gold: str, category: int, options: dict[str, str] | None = None
) -> float:
    """按类别的官方 lexical 分（Harbor `_score_one`）。"""
    if category == 5:
        opts = options or {}
        resolved = _resolve_cat5_answer(prediction, opts.get("a", ""), opts.get("b", ""))
        return 1.0 if _contains_refusal(resolved) else 0.0
    gold_text = gold
    if category == 3:
        gold_text = gold.split(";")[0].strip()
    pred_text = _latin_spans(prediction) or prediction
    if category == 1:
        return locomo_f1_multi(pred_text, gold_text)
    return locomo_f1(pred_text, gold_text)


class LoCoMoCalculator(MetricCalculator):
    """LoCoMo 指标计算器（F1 官方实现 + 按类 accuracy）。"""

    name: ClassVar[str] = "locomo"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        qa_items = _qa_from_task(inp.task)

        f1_scores: list[float] = []
        correct_flags: list[float] = []
        per_category_f1: dict[str, list[float]] = {}
        per_category_acc: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []

        for idx, qa in enumerate(qa_items):
            pred = prediction_for_item(inp.outputs, qa["question"], idx)
            category = int(qa.get("category") or 0)
            gold = str(qa.get("answer") or "")
            options = qa.get("options") if isinstance(qa.get("options"), dict) else {}
            f1 = score_locomo_f1(pred, gold, category, options)
            acc = 1.0 if self._judge_correct(pred, gold, qa["question"]) else 0.0
            f1_scores.append(f1)
            correct_flags.append(acc)

            cat_name = CATEGORY_MAPPING.get(category, f"category_{category}")
            per_category_f1.setdefault(cat_name, []).append(f1)
            per_category_acc.setdefault(cat_name, []).append(acc)
            details.append(
                {
                    "question": qa["question"],
                    "category": category,
                    "category_name": cat_name,
                    "f1": f1,
                    "correct": bool(acc),
                    "predicted": pred[:300],
                }
            )

        n = len(qa_items)
        values: dict[str, float] = {
            "f1": sum(f1_scores) / n if n else 0.0,
            "accuracy": sum(correct_flags) / n if n else 0.0,
        }
        by_category: dict[str, dict[str, float]] = {}
        for cat_name, scores in per_category_f1.items():
            accs = per_category_acc.get(cat_name, [])
            by_category[cat_name] = {
                "f1": sum(scores) / len(scores) if scores else 0.0,
                "accuracy": sum(accs) / len(accs) if accs else 0.0,
                "count": float(len(scores)),
            }
            values[f"f1_{cat_name}"] = by_category[cat_name]["f1"]
            values[f"accuracy_{cat_name}"] = by_category[cat_name]["accuracy"]

        bundle = MetricBundle(
            name=self.name,
            kind=self.kind,
            values=values,
            by_category=by_category,
            details=details,
        )
        return bundle

    def _judge_correct(self, pred: str, gold: str, question: str) -> bool:
        if self._judge is not None:
            return bool(self._judge(pred, gold, question))
        if not pred:
            return False
        if self._llm is None:
            from ...verifier import make_llm_judge

            self._llm = make_llm_judge("memory_qa", self._llm_config)
        return bool(self._llm.verify(pred, gold, question=question).is_pass)


def _qa_from_task(task: EvalTask | None) -> list[dict[str, Any]]:
    if task is None or not isinstance(task.data, dict):
        return []
    raw = task.data.get("qa") or []
    items: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict) and row.get("question"):
            items.append(row)
    return items
