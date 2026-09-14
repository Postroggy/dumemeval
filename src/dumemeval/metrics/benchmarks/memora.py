"""Memora 官方指标（FAMA 遗忘感知准确率）。

来源：benchmarks/conversation/Memora/evals/README.md + model_based_evaluator.py：

    FAMA = max(0, MPA − λ·(1 − FAA))
    MPA  = memory_presence 子题答对数 / 总数
    FAA  = forgetting_absence 子题答对数 / 总数
    λ    = N_forget / (N_presence + N_forget)

- 每题一个 FAMA ∈ [0,1]；n_p==0 且 n_f==0 → 0；无 forgetting 子题时 λ=0 → FAMA=MPA
- 子题判分 = LLM judge（官方多 judge 多数投票；本实现用注入 judge 或懒加载）
- 聚合：按 (task, period) 桶取题级 FAMA 均值 ×100（官方 README）
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from .locomo import JudgeFn


def fama_score(
    memory_presence_correct: int,
    memory_presence_total: int,
    forgetting_absence_correct: int,
    forgetting_absence_total: int,
) -> float:
    """官方 fama_score（model_based_evaluator.py L92-112）。"""
    n_p = memory_presence_total
    n_f = forgetting_absence_total
    if n_p == 0 and n_f == 0:
        return 0.0
    mpa = memory_presence_correct / n_p if n_p > 0 else 0.0
    faa = forgetting_absence_correct / n_f if n_f > 0 else 1.0
    lam = n_f / (n_p + n_f) if (n_p + n_f) > 0 else 0.0
    return max(0.0, mpa - lam * (1.0 - faa))


class MemoraCalculator(MetricCalculator):
    """Memora：FAMA（MPA/FAA 加权），按 task 分桶。"""

    name: ClassVar[str] = "memora"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        questions = data.get("questions") or []
        by_task: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        famas: list[float] = []
        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            query = str(q.get("question") or "")
            task = str(q.get("task") or "unknown")
            evaluation = q.get("evaluation") or {}
            raw_subs = evaluation.get("evaluation_questions") if isinstance(evaluation, dict) else []
            sub_questions: list[Any] = list(raw_subs) if raw_subs else []
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output

            n_p = n_f = c_p = c_f = 0
            sub_details: list[dict[str, Any]] = []
            for sub in sub_questions:
                if not isinstance(sub, dict):
                    continue
                sub_q = str(sub.get("evaluation_question") or "")
                expected = str(sub.get("expected_answer") or "").lower()
                eval_type = str(sub.get("evaluation_type") or "")
                answer = self._judge_yes_no(pred, sub_q, query)
                ok = answer == expected
                if eval_type == "memory_presence":
                    n_p += 1
                    c_p += 1 if ok else 0
                elif eval_type == "forgetting_absence":
                    n_f += 1
                    c_f += 1 if ok else 0
                sub_details.append(
                    {
                        "question": sub_q[:120],
                        "expected": expected,
                        "answer": answer,
                        "evaluation_type": eval_type,
                        "is_correct": ok,
                    }
                )
            score = fama_score(c_p, n_p, c_f, n_f)
            famas.append(score)
            by_task.setdefault(task, []).append(score)
            details.append(
                {
                    "idx": idx,
                    "task": task,
                    "fama": score,
                    "mpa": c_p / n_p if n_p else 0.0,
                    "faa": c_f / n_f if n_f else 1.0,
                    "lambda": n_f / (n_p + n_f) if (n_p + n_f) else 0.0,
                    "sub_questions": sub_details,
                }
            )

        values: dict[str, float] = {"fama": (sum(famas) / len(famas) * 100) if famas else 0.0}
        by_category: dict[str, dict[str, float]] = {}
        for task, scores in by_task.items():
            by_category[task] = {
                "fama": (sum(scores) / len(scores) * 100) if scores else 0.0,
                "count": float(len(scores)),
            }
            values[f"fama_{task}"] = by_category[task]["fama"]
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )

    def _judge_yes_no(self, pred: str, sub_question: str, question: str) -> str:
        """子题 yes/no 判分：注入 judge 返回 bool，否则懒加载 LLM。

        空 pred 返回 ""（不等于任何 expected，恒判错）——返回 "no" 会在
        expected=="no" 时把空输出判对（forgetting_absence 题虚高）。
        """
        if not pred:
            return ""
        if self._judge is not None:
            return "yes" if self._judge(pred, sub_question, question) else "no"
        if self._llm is None:
            from ...verifier import make_llm_judge

            # memory_qa：判"预测是否包含子题要求的信息"（此前误用
            # math_equivalence 数学等价模板，语义错配）
            self._llm = make_llm_judge("memory_qa", self._llm_config)
        verdict = self._llm.verify(pred, sub_question, question=question)
        return "yes" if verdict.is_pass else "no"
