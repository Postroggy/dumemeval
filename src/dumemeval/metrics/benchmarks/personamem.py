"""PersonaMem 官方指标（v1 确定性 MCQ 判分）。

来源：benchmarks/conversation/PersonaMem/inference.py ``extract_answer``（L106-136）：
- 答案 = 选项字母集合（a-d）
- ``correct_answer`` 列存 ``(c)`` 格式（prepare_blocks.py L927: '(' + chr(97 + correct_index) + ')'）
- 判定：pred_options == {correct} 即对（集合相等，忽略顺序）
- 从预测文本提取字母：优先括号内 (a-d)，否则裸字母 a-d
- 支持 ``<final_answer>`` 标签剥离

确定性判分，无 LLM judge。按 7 类 question_type 分桶报告 accuracy。
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind

# 官方 extract_answer 的正则（inference.py L108-113）
_PAREN_RE = re.compile(r"\(([a-d])\)")
_BARE_RE = re.compile(r"\b([a-d])\b")


def extract_options(text: str) -> set[str]:
    """官方 _extract_only_options：优先括号内字母，否则裸字母。"""
    lowered = (text or "").lower()
    in_parens = _PAREN_RE.findall(lowered)
    if in_parens:
        return set(in_parens)
    return set(_BARE_RE.findall(lowered))


def is_correct(predicted: str, correct_answer: str) -> bool:
    """官方 extract_answer 的判定核心。"""
    correct = correct_answer.lower().strip("() ")
    if not correct:
        return False

    cleaned = (predicted or "").strip()
    if "<final_answer>" in cleaned:
        cleaned = cleaned.split("<final_answer>")[-1].strip()
    if cleaned.endswith("</final_answer>"):
        cleaned = cleaned[: -len("</final_answer>")].strip()

    pred_options = extract_options(cleaned)
    if pred_options == {correct}:
        return True
    # 官方 fallback：用完整响应再试一次（预测被截断等情况）
    response_options = extract_options(predicted or "")
    return response_options == {correct}


class PersonaMemCalculator(MetricCalculator):
    """PersonaMem：MCQ 选项字母匹配 accuracy，按 question_type 分桶。"""

    name: ClassVar[str] = "personamem"
    kind: ClassVar[MetricKind] = "benchmark"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        questions = data.get("questions") or []
        by_type: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        n = 0
        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            n += 1
            query = str(q.get("question") or "")
            correct = str(q.get("correct_answer") or "")
            qtype = str(q.get("question_type") or "unknown")
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                # 位置兜底：outputs 与 questions 同序时
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output
            ok = is_correct(pred, correct)
            by_type.setdefault(qtype, []).append(1.0 if ok else 0.0)
            details.append(
                {
                    "idx": idx,
                    "question_type": qtype,
                    "correct_answer": correct,
                    "predicted": pred[:200],
                    "is_correct": ok,
                }
            )

        values: dict[str, float] = {
            "accuracy": sum(v for vs in by_type.values() for v in vs) / n if n else 0.0
        }
        by_category: dict[str, dict[str, float]] = {}
        for qtype, scores in by_type.items():
            by_category[qtype] = {
                "accuracy": sum(scores) / len(scores) if scores else 0.0,
                "count": float(len(scores)),
            }
            values[f"accuracy_{qtype}"] = by_category[qtype]["accuracy"]
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )
