"""EverMemBench-Dynamic 官方指标（MC 规则判分 + OE LLM judge）。

来源：benchmarks/security/EverMemBench/eval/src/core/evaluator.py：
- ``_evaluate_mc``（L224-254）：直接比对字母。
    - ``[xxx]`` 失败标记开头 → 恒错
    - golden 从 ``A. Option text`` 提取首字母
    - generated 用 ``_parse_mc_answer`` 多模式正则提取
- ``_parse_mc_answer``（L260-299）：直接单字母 / ``\b([ABCD])[.):,\\s]`` /
  "answer is X" / 首尾裸字母，解析失败返回原串（恒错）
- OE（open_ended）：LLM judge 输出 ``{"label": "CORRECT"}``，宽容式
  （gold 是简洁关键信息，回答包含相同关键信息即 CORRECT；日期窗口 ±1 天可接受）
- 聚合：Accuracy = correct / total，按 question_type（MC/OE）和
  question_id 前缀（major/minor）分桶

MC 全确定性；OE 无注入 judge 时懒加载 LLMJudgeVerifier 走上方官方 llm_judge
模板（宽容式：包含 gold 关键信息即 CORRECT、日期 ±1 天可接受），判定
"CORRECT" in 输出（官方 judge 输出 JSON label）。
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from .locomo import JudgeFn

# 官方 llm_judge 模板（EverMemBench/eval/config/prompts.yaml llm_judge，逐字；
# {{"label"}} 为 .format 转义，调用方同样用 .format 填充）
OE_JUDGE_SYSTEM_PROMPT = (
    "You are an expert grader that determines if answers to questions match a gold standard answer."
)

OE_JUDGE_USER_PROMPT = """Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. You will be given:
    (1) a question (about a multi-person group chat),
    (2) a 'gold' (ground truth) answer,
    (3) a generated answer
    which you will score as CORRECT/WRONG.

    The questions are about events, facts, or details mentioned in multi-person group chat conversations.
    The gold answer is usually a concise answer that includes the key information.

    For example:
    Question: What project was announced on January 9th?
    Gold answer: Carbon Emission Accounting Platform

    The generated answer might be longer, but you should be generous with your grading -
    as long as it contains the same key information as the gold answer, it should be CORRECT.

    For time-related questions, the gold answer will be a specific date/time.
    The generated answer might use different formats (e.g., "May 7th" vs "7 May" vs "2025-05-07"),
    but as long as it refers to the same date/time, it should be CORRECT.

    For the specific window of date, a +/- 1 day difference is acceptable due to timezone processing variations.

    For multiple choice questions where the gold answer is a letter (A/B/C/D),
    the generated answer should match exactly to be CORRECT.

    Now grade this:
    Question: {question}
    Gold answer: {golden_answer}
    Generated answer: {generated_answer}

    First, provide a short (one sentence) explanation of your reasoning,
    then finish with CORRECT or WRONG.
    Do NOT include both CORRECT and WRONG in your response.

    Return the label in JSON format with the key "label": {{"label": "CORRECT"}} or {{"label": "WRONG"}}
"""

# 官方 _parse_mc_answer（evaluator.py L260-299）
_PATTERN_DELIM = re.compile(r"\b([ABCD])[.):,\s]")
_PATTERN_ANSWER_IS = re.compile(r"(?:answer|choice|option|select)[:\s]+([ABCD])\b", re.IGNORECASE)


def parse_mc_answer(response: str) -> str:
    """官方 _parse_mc_answer。"""
    response = (response or "").strip().upper()
    if not response:
        return ""

    if len(response) == 1 and response in "ABCD":
        return response

    match = _PATTERN_DELIM.search(response)
    if match:
        return match.group(1)

    match = _PATTERN_ANSWER_IS.search(response)
    if match:
        return match.group(1).upper()

    if response[0] in "ABCD" and (len(response) == 1 or not response[1].isalpha()):
        return response[0]
    if response[-1] in "ABCD" and (len(response) == 1 or not response[-2].isalpha()):
        return response[-1]

    return response


def evaluate_mc(generated: str, golden: str) -> bool:
    """官方 _evaluate_mc。"""
    generated = (generated or "").strip()
    if generated.startswith("[") and generated.endswith("]"):
        return False

    golden = golden.strip().upper()
    if len(golden) > 1 and golden[0] in "ABCD" and golden[1] in ".):":
        golden = golden[0]

    parsed = parse_mc_answer(generated)
    return parsed == golden


class EverMemBenchDynamicCalculator(MetricCalculator):
    """EverMemBench-Dynamic：Accuracy（MC 规则 / OE judge）。"""

    name: ClassVar[str] = "evermembench_dynamic"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        questions = data.get("questions") or []
        by_mode: dict[str, list[float]] = {}
        by_prefix: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        n = 0
        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            n += 1
            query = str(q.get("question") or q.get("Q") or "")
            golden = str(q.get("answer") or q.get("A") or "")
            options = q.get("options")
            mode = "multiple_choice" if isinstance(options, dict) and options else "open_ended"
            qid = str(q.get("id") or "")
            prefix = qid.split("_")[0] if qid else "unknown"
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output

            if mode == "multiple_choice":
                ok = evaluate_mc(pred, golden)
            else:
                ok = self._judge_oe(pred, golden, query)
            score = 1.0 if ok else 0.0
            by_mode.setdefault(mode, []).append(score)
            by_prefix.setdefault(prefix, []).append(score)
            details.append(
                {
                    "idx": idx,
                    "id": qid,
                    "mode": mode,
                    "prefix": prefix,
                    "is_correct": ok,
                    "predicted": pred[:200],
                }
            )

        values: dict[str, float] = {
            "accuracy": sum(v for vs in by_mode.values() for v in vs) / n if n else 0.0
        }
        by_category: dict[str, dict[str, float]] = {}
        for mode, scores in by_mode.items():
            by_category[mode] = {
                "accuracy": sum(scores) / len(scores) if scores else 0.0,
                "count": float(len(scores)),
            }
            values[f"accuracy_{mode}"] = by_category[mode]["accuracy"]
        for prefix, scores in by_prefix.items():
            by_category[prefix] = {
                "accuracy": sum(scores) / len(scores) if scores else 0.0,
                "count": float(len(scores)),
            }
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )

    def _judge_oe(self, pred: str, gold: str, question: str) -> bool:
        if not pred:
            return False
        if self._judge is not None:
            return bool(self._judge(pred, gold, question))
        if self._llm is None:
            from ...verifier import make_llm_judge

            self._llm = make_llm_judge("task_success", self._llm_config)
        # 官方 llm_judge（eval/config/prompts.yaml L115-150，逐字）：
        # 宽容式判分——包含 gold 关键信息即可；日期格式无关；±1 天可接受
        verdict = self._llm.verify_with_prompt(
            OE_JUDGE_USER_PROMPT.format(question=question, golden_answer=gold, generated_answer=pred),
            system_prompt=OE_JUDGE_SYSTEM_PROMPT,
        )
        return "CORRECT" in verdict.raw.upper()
