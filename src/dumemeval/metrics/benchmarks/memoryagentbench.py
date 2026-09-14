"""MemoryAgentBench 官方指标（按能力路由）。

来源：benchmarks/agentic/MemoryAgentBench/utils/eval_other_utils.py + README L173-185：

| 能力 | source 前缀 | 指标 |
|---|---|---|
| AR（Accurate Retrieval） | event_qa, ruler_qa1, ruler_qa2 | substring_exact_match（GT ∈ pred，多 GT 取 max） |
| CR（Conflict Resolution） | fact_mh, fact_sh | substring_exact_match |
| LRU | detective_qa | exact_match（严格：label: 43 会被判错） |
| TTL | icl_* | exact_match（先 parse_output 提 Answer: 前缀后内容） |
| Recsys | recsys_* | Recall@5（编辑距离匹配 entity2id；本实现不支持，calculate 层跳过并留痕，不进分母） |
| LongMemEval | longmemeval* | LLM judge（本实现用注入 judge，无则懒加载） |
| InfBench | infbench_* | LLM judge F1（本实现用注入 judge） |

- ``normalize_answer``：lowercase → 去标点 → 去 a/an/the → 合并空白
- ``substring_exact_match``：GT 是 pred 的子串（方向：答案在预测里）
- ``exact_match``：标准化后完全相等
- 多 ground truth 取 max（drqa_metric_max_over_ground_truths）
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from .locomo import JudgeFn


def normalize_answer(text: str) -> str:
    """官方 normalize_answer（eval_other_utils.py L32-48）。"""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def substring_exact_match(prediction: str, ground_truth: str) -> bool:
    """官方 substring_exact_match_score：GT ∈ pred。"""
    return normalize_answer(ground_truth) in normalize_answer(prediction)


def exact_match(prediction: str, ground_truth: str) -> bool:
    """官方 drqa_exact_match_score。"""
    return normalize_answer(prediction) == normalize_answer(ground_truth)


def metric_max_over_ground_truths(metric_fn: Any, prediction: str, ground_truths: Any) -> float:
    """官方 drqa_metric_max_over_ground_truths：多 GT 取 max。"""
    if isinstance(ground_truths, str):
        gt_list: list[str] = [ground_truths]
    elif ground_truths and isinstance(ground_truths[0], list):
        gt_list = [gt for sub in ground_truths for gt in sub]
    else:
        gt_list = list(ground_truths)
    if not gt_list:
        return 0.0
    return float(max(metric_fn(prediction, gt) for gt in gt_list))


def parse_output(output_text: str, answer_prefix: str = "Answer:") -> str | None:
    """官方 parse_output：提取 Answer: 前缀后的内容，找不到取整行。"""
    text = output_text or ""
    patterns = [
        re.compile(f"(?:{answer_prefix})(.*)(?:\n|$)", flags=re.IGNORECASE),
        re.compile(r"(?:^)(.*)(?:\n|$)"),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            extracted = match[1].strip()
            clean = re.sub(f"^{re.escape(answer_prefix)}", "", extracted, flags=re.IGNORECASE).strip()
            return clean
    return None


class MemoryAgentBenchCalculator(MetricCalculator):
    """MemoryAgentBench：按 source 路由到各自官方指标。"""

    name: ClassVar[str] = "memoryagentbench"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        samples = data.get("samples") or []
        by_source: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        total_questions = 0
        for idx, sample in enumerate(samples):
            if not isinstance(sample, dict):
                continue
            source = str(sample.get("source") or "unknown")
            if source.startswith("recsys"):
                # Recall@5 需 entity2id 表 + 编辑距离匹配，本实现不支持。
                # 不计入分母（恒 0 进聚合会系统性拉低 accuracy），跳过并留痕。
                for question in sample.get("questions") or []:
                    details.append(
                        {
                            "source": source,
                            "question": str(question)[:100],
                            "skipped": True,
                            "reason": "recsys Recall@5 unsupported (entity2id required); excluded from denominator",
                        }
                    )
                continue
            questions = sample.get("questions") or []
            answers = sample.get("answers") or []
            for q_idx, question in enumerate(questions):
                total_questions += 1
                query = str(question)
                gts = answers[q_idx] if q_idx < len(answers) else []
                pred = next((item.output for item in inp.outputs if item.query == query), "")
                if not pred:
                    outputs = list(inp.outputs)
                    global_idx = sum(len(s.get("questions") or []) for s in samples[:idx]) + q_idx
                    if global_idx < len(outputs):
                        pred = outputs[global_idx].output
                score = self._score_one(source, pred, gts, query)
                by_source.setdefault(source, []).append(score)
                details.append(
                    {
                        "idx": idx,
                        "source": source,
                        "question": query[:100],
                        "score": score,
                        "predicted": pred[:200],
                    }
                )

        values: dict[str, float] = {
            "accuracy": sum(v for vs in by_source.values() for v in vs) / total_questions
            if total_questions
            else 0.0
        }
        by_category: dict[str, dict[str, float]] = {}
        for src, scores in by_source.items():
            by_category[src] = {
                "accuracy": sum(scores) / len(scores) if scores else 0.0,
                "count": float(len(scores)),
            }
            values[f"accuracy_{src}"] = by_category[src]["accuracy"]
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )

    def _score_one(self, source: str, pred: str, gts: Any, query: str) -> float:
        if not pred:
            return 0.0
        if source.startswith(("event_qa", "ruler_qa", "fact_mh", "fact_sh", "factconsolidation")):
            return metric_max_over_ground_truths(substring_exact_match, pred, gts)
        if source.startswith(("detective", "icl_")):
            parsed = parse_output(pred) or pred
            return metric_max_over_ground_truths(exact_match, parsed, gts)
        # LongMemEval / InfBench：LLM judge（recsys 在 calculate 层已跳过）
        return 1.0 if self._judge_llm(pred, gts, query) else 0.0

    def _judge_llm(self, pred: str, gts: Any, query: str) -> bool:
        gold = gts[0] if isinstance(gts, list) and gts else str(gts)
        if self._judge is not None:
            return bool(self._judge(pred, gold, query))
        if self._llm is None:
            from ...verifier import make_llm_judge

            self._llm = make_llm_judge("task_success", self._llm_config)
        return bool(self._llm.verify(pred, gold, task=query).is_pass)
