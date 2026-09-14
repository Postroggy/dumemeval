"""BEAM 官方指标（LLM-as-judge 按 rubric 打分）。

来源：benchmarks/conversation/BEAM/src/：
- ``run_evaluation.py`` + ``compute_metrics.py``：
  - 9/10 类：对 rubric 每一条目用 judge 打 0/0.5/1，llm_judge_score = Σscore / len(rubric)
  - event_ordering 特殊：event_ordering_score = Kendall τ_b 归一化 × F1 + llm_judge_score
- ``report_results.py``：每类 10 题平均
- 判定：LLM judge（unified_llm_judge_base_prompt 输出 {"score": 1.0|0.5|0.0, "reason"}）

本实现：judge 对 rubric 逐条打 0/1（简化二值，0.5 需注入 judge 支持），
取平均得 llm_judge_score。event_ordering 官方口径 = τ_b_norm × F1
（compute_metrics.py L270-308）：本实现为确定性近似——normalize 贪心对齐
（无 embedding 语义对齐，改写事件会漏配）+ 手写 τ_b，details 里带
event_ordering_tau_b / f1 分量。
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from .locomo import JudgeFn

JUDGE_PROMPT_TEMPLATE = """You are an expert judge. Given a question, a rubric item, and a model response, score whether the response satisfies the rubric item.

Score:
- 1.0: fully satisfies
- 0.5: partially satisfies
- 0.0: does not satisfy

Question: {question}

Rubric item: {rubric}

Model Response: {response}

Return your judgment strictly in JSON format:
{{"score": 1.0 or 0.5 or 0.0, "reason": "<short explanation>"}}
"""


def build_judge_prompt(question: str, rubric: str, response: str) -> str:
    return JUDGE_PROMPT_TEMPLATE.format(question=question, rubric=rubric, response=response)


def parse_score(raw: str) -> float | None:
    """从 judge JSON 提取 score（0/0.5/1）；解析失败返回 None。"""
    if not raw:
        return None
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            score = float(data.get("score", -1))
            if score in (0.0, 0.5, 1.0):
                return score
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _normalize_event(text: str) -> str:
    """事件文本归一（lower + 去标点 + 合并空白）——对齐用的确定性代理。"""
    lowered = (text or "").lower()
    stripped = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(stripped.split())


def _split_events(pred: str) -> list[str]:
    """模型输出 → 事件列表：按行切，剥序号前缀（1. / 1) / - / *）。"""
    events: list[str] = []
    for line in (pred or "").splitlines():
        line = line.strip()
        line = re.sub(r"^(?:\d+[.)]|[-*•])\s*", "", line)
        if line:
            events.append(line)
    return events


def kendall_tau_b(x: list[int], y: list[int]) -> float:
    """Kendall τ_b（官方用 scipy.stats.kendalltau；此处手写避免 scipy 依赖）。

    τ_b = (c − d) / sqrt((n₀ − n_x)(n₀ − n_y))，n₀ = n(n−1)/2，
    n_x / n_y 为 x / y 中的并列对数。
    """
    n = len(x)
    if n < 2:
        return 1.0 if n == 1 else 0.0
    concordant = discordant = 0
    x_ties = y_ties = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = x[i] - x[j], y[i] - y[j]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                x_ties += 1
            elif dy == 0:
                y_ties += 1
            elif dx * dy > 0:
                concordant += 1
            else:
                discordant += 1
    n0 = n * (n - 1) / 2
    denom_x = n0 - x_ties
    denom_y = n0 - y_ties
    if denom_x <= 0 or denom_y <= 0:
        return 0.0
    return float((concordant - discordant) / (denom_x * denom_y) ** 0.5)


def event_ordering_score(pred: str, reference_events: list[str]) -> tuple[float, dict[str, float]]:
    """官方 event_ordering_score 的确定性近似。

    官方（compute_metrics.py L270-308）：embedding 语义对齐系统/参考事件 →
    kendalltau → τ_b_norm=(τ+1)/2 → final = τ_b_norm × F1。
    本实现不依赖 embedding/LLM：normalize 后精确贪心对齐（对不上的事件不计），
    对齐子序列上算 τ_b 与集合 F1。近似成分：无语义对齐（改写的事件会漏配）。
    """
    pred_events = _split_events(pred)
    ref_norm = [_normalize_event(e) for e in reference_events]
    pred_norm = [_normalize_event(e) for e in pred_events]

    # 贪心对齐：pred 每个事件找第一个未用的相同 reference（保 pred 顺序）
    used: set[int] = set()
    aligned_ref_idx: list[int] = []
    for p in pred_norm:
        for j, r in enumerate(ref_norm):
            if j not in used and r == p:
                used.add(j)
                aligned_ref_idx.append(j)
                break

    matched = len(aligned_ref_idx)
    if matched == 0 or not pred_events or not reference_events:
        return 0.0, {"tau_b": 0.0, "f1": 0.0, "matched": 0.0}

    # F1：对齐集合 vs 两序列长度（官方 f1 为对齐事件集合 F1）
    precision = matched / len(pred_events)
    recall = matched / len(reference_events)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # τ_b：pred 顺序的 ref 索引 vs 同一集合的排序（真实顺序）
    tau = kendall_tau_b(list(range(matched)), aligned_ref_idx)
    tau_norm = (tau + 1) / 2
    final = tau_norm * f1
    return final, {"tau_b": tau, "tau_b_norm": tau_norm, "f1": f1, "matched": float(matched)}


class BeamCalculator(MetricCalculator):
    """BEAM：llm_judge_score（rubric 逐条打分平均）。"""

    name: ClassVar[str] = "beam"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        samples = data.get("samples") or []
        by_type: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        n = 0
        for idx, sample in enumerate(samples):
            if not isinstance(sample, dict):
                continue
            n += 1
            query = str(sample.get("question") or "")
            rubrics = list(sample.get("rubrics") or [])
            qtype = str(sample.get("question_type") or "unknown")
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output
            score, extra = self._score_one(pred, rubrics, query, qtype)
            by_type.setdefault(qtype, []).append(score)
            details.append(
                {
                    "idx": idx,
                    "question_type": qtype,
                    "llm_judge_score": score,
                    "predicted": pred[:200],
                    **extra,
                }
            )

        values: dict[str, float] = {
            "llm_judge_score": sum(v for vs in by_type.values() for v in vs) / n if n else 0.0
        }
        by_category: dict[str, dict[str, float]] = {}
        for qtype, scores in by_type.items():
            by_category[qtype] = {
                "llm_judge_score": sum(scores) / len(scores) if scores else 0.0,
                "count": float(len(scores)),
            }
            values[f"llm_judge_score_{qtype}"] = by_category[qtype]["llm_judge_score"]
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )

    def _score_one(
        self, pred: str, rubrics: list[str], query: str, qtype: str = "unknown"
    ) -> tuple[float, dict[str, float]]:
        """返回 (score, extra_details)。event_ordering 走官方 τ_b×F1（确定性近似）。"""
        if not pred or not rubrics:
            return 0.0, {}
        if qtype == "event_ordering":
            final, parts = event_ordering_score(pred, rubrics)
            return final, {f"event_ordering_{k}": v for k, v in parts.items()}
        total = 0.0
        for rubric in rubrics:
            if self._judge is not None:
                score = 1.0 if self._judge(pred, rubric, query) else 0.0
            else:
                if self._llm is None:
                    from ...verifier import make_llm_judge

                    self._llm = make_llm_judge("task_success", self._llm_config)
                prompt = build_judge_prompt(query, rubric, pred)
                verdict = self._llm.verify_with_prompt(prompt)
                score = parse_score(verdict.raw) or 0.0
            total += score
        return total / len(rubrics), {}
