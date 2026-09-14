"""CL-bench 官方指标（Solving Rate = LLM judge 全有或全无）。

来源：benchmarks/conversation/CL-bench/eval.py：
- ``grading_prompt``（L93-126）：严格 all-or-nothing，必须满足 rubrics 每一条才给 1 分
- judge 输出 JSON：{"Grading Rationale", "List of Requirement Satisfaction Status", "Overall Score": 0|1}
- 空输出 / API 失败 / JSON 解析失败一律计 0
- Solving Rate = score_1 / total（eval.py L393-395），按 context_category 分桶

判定：LLM judge。无注入 judge 时懒加载 LLMJudgeVerifier 用官方 prompt。
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from .locomo import JudgeFn

GRADING_PROMPT_TEMPLATE = """Starting now, you are a rigorous instruction-following grading teacher. Your task is to accurately grade and score student answers based on the 【Rubrics】.

Grading Criteria
This is a strict, all-or-nothing grading system. The final score is binary.
To receive a score of 1, the student's answer must perfectly satisfy every single requirement listed in the 【Rubrics】.
If even one requirement is not fully met, the final score will be 0.

Grading Process
Please strictly follow the steps below for analysis—no steps may be skipped:
Step 1: Analyze the Standard Answer
List all explicit requirements in the 【Rubrics】 item by item (including format, content, quantity, order, etc.).
Identify implicit requirements in the 【Rubrics】 (e.g., language style, logical structure).
Define specific evaluation criteria for each requirement (e.g., "must include X," "must not exceed Y").
Step 2: Check Each Requirement Against the Student's Answer
For every requirement in the 【Rubrics】, verify one by one whether the student's answer fully satisfies it.
Step 3: Self-Reflection
Before giving the final score, you must conduct the following checks:
  Completeness Check: Whether all requirements in the standard answer have been reviewed with no omissions.
  Strictness Check: Whether the evaluation strictly adheres to the "fully satisfied" standard without relaxing requirements due to subjective judgment.
  Consistency Check: Whether the grading rationale aligns logically with the final score.
  Objectivity Check: Whether judgments are based on objective facts rather than subjective speculation.

Output Format Requirements
【Grading Rationale】: xxx
【List of Requirement Satisfaction Status】: [x₁, x₂, …, xᵢ, …, xₙ] (where n is the total number of requirements in the 【Rubrics】, and xᵢ indicates whether the student's answer meets the i-th requirement, with values "yes"/"no")
【Overall Score】: x points (x is an integer, either 0 or 1.)

Content to Be Graded
【Rubrics】:
{rubrics_text}
【Student Response】:
{model_output}

Please strictly output ONLY the following JSON format (do not output any other content):
{{
  "Grading Rationale": "Your detailed grading rationale",
  "List of Requirement Satisfaction Status": ["yes", "no", ...],
  "Overall Score": 0 or 1
}}
"""


def build_grading_prompt(rubrics: list[str], model_output: str) -> str:
    """官方 grading_prompt。"""
    rubrics_text = "\n".join(f"- {r}" for r in rubrics)
    return GRADING_PROMPT_TEMPLATE.format(rubrics_text=rubrics_text, model_output=model_output)


def parse_overall_score(raw: str) -> int | None:
    """官方：从 judge JSON 提取 Overall Score；解析失败返回 None（计 0）。"""
    if not raw:
        return None
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            score = data.get("Overall Score")
            if score in (0, 1):
                return int(score)
        except (json.JSONDecodeError, ValueError):
            pass
    # fallback：文本里找 0/1 分
    match = re.search(r"Overall Score['\"]?\s*[:：]?\s*(\d+)", raw)
    if match and match.group(1) in ("0", "1"):
        return int(match.group(1))
    return None


class CLBenchCalculator(MetricCalculator):
    """CL-bench：Solving Rate（LLM judge 全有或全无）。"""

    name: ClassVar[str] = "clbench"
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
            query = str(sample.get("question") or "")
            rubrics = list(sample.get("rubrics") or [])
            category = str(sample.get("context_category") or "unknown")
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output
            score = self._score_one(pred, rubrics, query)
            by_cat.setdefault(category, []).append(score)
            details.append(
                {
                    "idx": idx,
                    "context_category": category,
                    "score": score,
                    "predicted": pred[:200],
                }
            )

        values: dict[str, float] = {
            "solving_rate": sum(v for vs in by_cat.values() for v in vs) / n if n else 0.0
        }
        by_category: dict[str, dict[str, float]] = {}
        for cat, scores in by_cat.items():
            by_category[cat] = {
                "solving_rate": sum(scores) / len(scores) if scores else 0.0,
                "count": float(len(scores)),
            }
            values[f"solving_rate_{cat}"] = by_category[cat]["solving_rate"]
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )

    def _score_one(self, pred: str, rubrics: list[str], query: str) -> float:
        if not pred or not rubrics:
            return 0.0
        if self._judge is not None:
            # 注入 judge：rubrics 必须传给 judge（官方 all-or-nothing 语义需要
            # 逐条 rubric；此前传空 gold 会丢判分依据）
            return 1.0 if self._judge(pred, "\n".join(rubrics), query) else 0.0
        if self._llm is None:
            from ...verifier import make_llm_judge

            self._llm = make_llm_judge("task_success", self._llm_config)
        prompt = build_grading_prompt(rubrics, pred)
        verdict = self._llm.verify_with_prompt(prompt)
        score = parse_overall_score(verdict.raw)
        return 1.0 if score == 1 else 0.0
