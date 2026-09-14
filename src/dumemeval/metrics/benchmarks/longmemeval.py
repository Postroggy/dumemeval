"""LongMemEval 官方指标（LLM judge + abstention）。

来源：benchmarks/conversation/LongMemEval/src/evaluation/evaluate_qa.py：
- ``get_anscheck_prompt``（L24-43）：按 question_type 分 5 类模板 +
  abstention 专用模板（判"正确识别不可答"）
- 判定：``'yes' in eval_response.lower()``（L112-113）
- abstention：question_id 以 ``_abs`` 结尾（L101），单独报 Abstention Accuracy，
  不计入 Overall
- 聚合：print_qa_metrics.py —— Overall Accuracy（非 abstention）+
  Task-averaged Accuracy + Abstention Accuracy
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from .locomo import JudgeFn

# 官方 evaluate_qa.py 的 5 类 judge 模板（逐字，abstention 单独）
_COMMON = (
    "I will give you a question, a correct answer, and a response from a model. "
    "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
    "If the response is equivalent to the correct answer or contains all the intermediate steps "
    "to get the correct answer, you should also answer yes. If the response only contains a subset "
    "of the information required by the answer, answer no."
)
_TEMPORAL_EXTRA = (
    " In addition, do not penalize off-by-one errors for the number of days. "
    "If the question asks for the number of days/weeks/months, etc., and the model makes "
    "off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct."
)
_KNOWLEDGE_EXTRA = (
    " If the response contains some previous information along with an updated answer, "
    "the response should be considered as correct as long as the updated answer is the required answer."
)
_PREFERENCE_TEMPLATE = (
    "I will give you a question, a rubric for desired personalized response, and a response from a model. "
    "Please answer yes if the response satisfies the desired response. Otherwise, answer no. "
    "The model does not need to reflect all the points in the rubric. The response is correct as long as "
    "it recalls and utilizes the user's personal information correctly."
)
_ABSTENTION_TEMPLATE = (
    "I will give you an unanswerable question, an explanation, and a response from a model. "
    "Please answer yes if the model correctly identifies the question as unanswerable. "
    "The model could say that the information is incomplete, or some other information is given "
    "but the asked information is not."
)

# question_type 数据值 → 官方 judge 类别
TYPE_TO_JUDGE: dict[str, str] = {
    "single_hop": "single-session-user",
    "assistant_previnfo": "single-session-assistant",
    "implicit_preference_v2": "single-session-preference",
    "two_hop": "multi-session",
    "multi_session_synthesis": "multi-session",
    "temp_reasoning_implicit": "temporal-reasoning",
    "temp_reasoning_explicit": "temporal-reasoning",
    "knowledge_update": "knowledge-update",
}


def build_anscheck_prompt(
    task: str, question: str, answer: str, response: str, abstention: bool = False
) -> str:
    """官方 get_anscheck_prompt。"""
    if abstention:
        return (
            f"{_ABSTENTION_TEMPLATE}\n\nQuestion: {question}\n\nExplanation: {answer}\n\n"
            f"Model Response: {response}\n\nDoes the model correctly identify the question as unanswerable? "
            "Answer yes or no only."
        )
    if task == "temporal-reasoning":
        body = _COMMON + _TEMPORAL_EXTRA
    elif task == "knowledge-update":
        body = _COMMON + _KNOWLEDGE_EXTRA
    elif task == "single-session-preference":
        body = _PREFERENCE_TEMPLATE
    else:
        body = _COMMON
    return (
        f"{body}\n\nQuestion: {question}\n\nCorrect Answer: {answer}\n\nModel Response: {response}\n\n"
        "Is the model response correct? Answer yes or no only."
    )


def judge_yes(response: str) -> bool:
    """官方判定：'yes' in eval_response.lower()。"""
    return "yes" in (response or "").lower()


class LongMemEvalCalculator(MetricCalculator):
    """LongMemEval：QA accuracy（LLM judge）+ abstention accuracy。"""

    name: ClassVar[str] = "longmemeval"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        questions = data.get("questions") or []
        normal_flags: list[float] = []
        abstention_flags: list[float] = []
        by_type: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        n = 0
        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            n += 1
            query = str(q.get("question") or "")
            answer = str(q.get("answer") or "")
            qid = str(q.get("question_id") or "")
            qtype = str(q.get("question_type") or "unknown")
            abstention = qid.endswith("_abs")
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output
            ok = self._judge_one(pred, answer, query, qtype, abstention)
            score = 1.0 if ok else 0.0
            if abstention:
                abstention_flags.append(score)
            else:
                normal_flags.append(score)
                by_type.setdefault(qtype, []).append(score)
            details.append(
                {
                    "idx": idx,
                    "question_id": qid,
                    "question_type": qtype,
                    "abstention": abstention,
                    "is_correct": ok,
                    "predicted": pred[:200],
                }
            )

        values: dict[str, float] = {}
        if normal_flags:
            values["accuracy"] = sum(normal_flags) / len(normal_flags)
        if abstention_flags:
            values["abstention_accuracy"] = sum(abstention_flags) / len(abstention_flags)
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

    def _judge_one(self, pred: str, answer: str, question: str, qtype: str, abstention: bool) -> bool:
        if not pred:
            return False
        task = TYPE_TO_JUDGE.get(qtype, "single-session-user")
        if self._judge is not None:
            return bool(self._judge(pred, answer, question))
        if self._llm is None:
            from ...verifier import make_llm_judge

            self._llm = make_llm_judge("task_success", self._llm_config)
        prompt = build_anscheck_prompt(task, question, answer, pred, abstention)
        verdict = self._llm.verify_with_prompt(prompt)
        return judge_yes(verdict.raw)
