"""MemoryCD 官方指标（跨域个性化，确定性）。

来源：benchmarks/conversation/MemoryCD/eval_core.py：
- rating_prediction：MAE + RMSE（L295-311）
- review_summarization / review_generation：ROUGE-1/L(f1)（L315-392）
- item_ranking：NDCG@K / Recall@K（L394-457）

所有指标确定性，无 LLM judge（LLM 仅作为被测对象）。
"""

from __future__ import annotations

import math
import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind


def parse_rating(text: str) -> float | None:
    """官方容错：从 agent 输出解析 1-5 评分（解析失败官方回退 3.0）。"""
    match = re.search(r"(\d+(?:\.\d+)?)", text or "")
    if match:
        value = float(match.group(1))
        if 1.0 <= value <= 5.0:
            return value
    return None


def mae(pred: float, target: float) -> float:
    return abs(pred - target)


def rouge_l_f1(prediction: str, reference: str) -> float:
    """ROUGE-L F1（最长公共子序列近似，基于 token）。"""
    p_tokens = (prediction or "").lower().split()
    r_tokens = (reference or "").lower().split()
    if not p_tokens or not r_tokens:
        return 0.0
    # LCS
    m, n = len(p_tokens), len(r_tokens)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if p_tokens[i - 1] == r_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[m][n]
    if lcs == 0:
        return 0.0
    precision = lcs / m
    recall = lcs / n
    return 2 * precision * recall / (precision + recall)


def ndcg_at_k(ranked: list[str], ground_truth: str, k: int = 5) -> float:
    """官方单相关项 NDCG@K（eval_core.py L417-427）。

    DCG 折扣分级：rank r 处命中得 1/log2(r+1)，IDCG=1.0（rank1）——
    rank1=1.0、rank2≈0.63、rank3=0.5（旧实现 0/1 化，rank2-5 同分，非官方）。
    """
    if not ranked or k <= 0:
        return 0.0
    for i, asin in enumerate(ranked[:k]):
        if asin == ground_truth:
            return 1.0 / math.log2(i + 2)
    return 0.0


def recall_at_k(ranked: list[str], ground_truth: str, k: int = 5) -> float:
    """官方 Recall@K（eval_core.py L429-432）：gt ∈ ranked[:k] 的 0/1。"""
    return 1.0 if ground_truth in ranked[:k] else 0.0


class MemoryCDCalculator(MetricCalculator):
    """MemoryCD：MAE/RMSE/ROUGE-L/NDCG@K/Recall@K。"""

    name: ClassVar[str] = "memorycd"
    kind: ClassVar[MetricKind] = "benchmark"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        tasks = data.get("tasks") or []
        rating_errors: list[float] = []
        rouge_scores: list[float] = []
        ndcg_scores: list[float] = []
        recall_scores: list[float] = []
        details: list[dict[str, Any]] = []
        n = 0
        for idx, task in enumerate(tasks):  # idx 用于 outputs 下标兜底
            if not isinstance(task, dict):
                continue
            n += 1
            query = str(task.get("query") or "")
            task_type = str(task.get("task_type") or "rating")
            target = task.get("target")
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output
            detail: dict[str, Any] = {"idx": idx, "task_type": task_type, "predicted": pred[:200]}

            if task_type == "rating":
                target_rating = float(target) if target is not None else 0.0
                parsed = parse_rating(pred)
                pred_rating = parsed if parsed is not None else 3.0  # 官方回退 3.0
                err = mae(pred_rating, target_rating)
                rating_errors.append(err)
                detail["mae"] = err
            elif task_type in ("summarization", "generation"):
                rouge = rouge_l_f1(pred, str(target or ""))
                rouge_scores.append(rouge)
                detail["rouge_l_f1"] = rouge
            elif task_type == "ranking":
                gt = str(target or "")
                ranked = re.findall(r"B0[0-9A-Z]{8}", pred.upper())
                ndcg = ndcg_at_k(ranked, gt, 5)
                rec = recall_at_k(ranked, gt, 5)
                ndcg_scores.append(ndcg)
                recall_scores.append(rec)
                detail["ndcg@5"] = ndcg
                detail["recall@5"] = rec
            details.append(detail)

        values: dict[str, float] = {}
        if rating_errors:
            values["mae"] = sum(rating_errors) / len(rating_errors)
            values["rmse"] = (sum(e * e for e in rating_errors) / len(rating_errors)) ** 0.5
        if rouge_scores:
            values["rouge_l_f1"] = sum(rouge_scores) / len(rouge_scores)
        if ndcg_scores:
            values["ndcg@5"] = sum(ndcg_scores) / len(ndcg_scores)
            values["recall@5"] = sum(recall_scores) / len(recall_scores)
        return MetricBundle(name=self.name, kind=self.kind, values=values, details=details)
