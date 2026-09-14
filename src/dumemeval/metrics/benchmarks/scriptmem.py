"""ScriptMem 官方指标（确定性 MCQ 判分，无 LLM judge）。

来源：benchmarks/conversation/ScriptMem/src/score_mcq.py：
- gold_letters（L34-42）：从 answer 文本提取行首 ``X.`` 字母（单/多/排序答案是有序文本列表）
- predicted_letters（L84-89）：
    - multi_select / ordering：predicted_ordered_letters —— 取最后一个括号内容，
      按 A-F 字母序提取，重复字母视为 malformed
    - single_choice：predicted_option_letters —— 多种格式（裸字母串/单字母括号/
      带标签 "(A) text"），返回有序去重集合
- score_item（L145-152）：
    - single_choice：gold 1 字母且 pred 1 字母且相等 → 1
    - multi_select：集合相等且 pred 无重复 → 1
    - ordering：gold == pred 顺序完全一致 → 1
- malformed（如重复字母、多个括号选项）一律 0 分

aggregate：accuracy = total / count，按 dataset / qa_type 分桶。
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind

ANSWER_RE = re.compile(r"^\s*([A-F])\.")


def gold_letters(answer: Any) -> list[str]:
    """官方 gold_letters。"""
    parts = answer if isinstance(answer, list) else [answer]
    letters: list[str] = []
    for part in parts:
        match = ANSWER_RE.match(str(part))
        if match:
            letters.append(match.group(1))
    return letters


def normalize_prediction_text(text: str) -> str:
    """官方 normalize_prediction_text（剥 \boxed / final answer: / </think>）。"""
    cleaned = str(text or "").strip()
    box_matches = list(re.finditer(r"\\box(?:ed)?\{([^}]*)(?:\}|$)", cleaned))
    if box_matches:
        return box_matches[-1].group(1).strip()
    lower = cleaned.lower()
    if "final answer:" in lower:
        index = lower.index("final answer:")
        cleaned = cleaned[index + len("final answer:") :].strip()
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1].strip()
    return cleaned


def predicted_ordered_letters(prediction: str) -> tuple[list[str], bool]:
    """官方 predicted_ordered_letters。"""
    paren_matches = list(re.finditer(r"[\(\[]([^)\]]*)[\)\]]", prediction))
    content = paren_matches[-1].group(1) if paren_matches else prediction
    letters = [letter.upper() for letter in re.findall(r"[A-Fa-f]", content)]
    if not letters:
        return [], False
    return letters, len(set(letters)) != len(letters)


def predicted_option_letters(prediction: str) -> tuple[list[str], bool]:
    """官方 predicted_option_letters。"""
    if re.fullmatch(r"[A-Fa-f]{1,5}", prediction):
        return [letter.upper() for letter in prediction], False
    if re.search(r"\(\s*[A-Fa-f]\s*\)\(\s*[A-Fa-f]\s*\)", prediction) or re.search(
        r"\[\s*[A-Fa-f]\s*\]\[\s*[A-Fa-f]\s*\]",
        prediction,
    ):
        return [], True

    options: set[str] = set()
    token_re = re.compile(r"\([^)]*\)|\[[^\]]*\]")
    for match in token_re.finditer(prediction):
        inner = match.group(0)[1:-1].strip()
        if not inner:
            continue

        single_letter_match = re.fullmatch(r"([A-Fa-f])", inner)
        if single_letter_match:
            options.add(single_letter_match.group(1).upper())
            continue

        labeled_text_match = re.match(r"^([A-Fa-f])\s*[.:]\s*.+$", inner)
        if labeled_text_match:
            options.add(labeled_text_match.group(1).upper())
            continue

        letters_only = re.sub(r"[^A-Za-z]", "", inner)
        if (
            letters_only
            and len(letters_only) <= 5
            and inner[0].upper() in {"A", "B", "C", "D", "E", "F"}
            and re.fullmatch(r"[A-Za-z ]+", inner)
        ):
            options.add(inner[0].upper())
    return sorted(options), False


def predicted_letters(prediction: str, qa_type: str = "") -> tuple[list[str], bool]:
    """官方 predicted_letters。"""
    normalized = normalize_prediction_text(prediction)
    if not normalized:
        return [], False
    if qa_type in {"multi_select", "ordering"}:
        return predicted_ordered_letters(normalized)
    return predicted_option_letters(normalized)


def score_item(qa_type: str, gold: list[str], pred: list[str], malformed: bool = False) -> float:
    """官方 score_item。"""
    if malformed:
        return 0.0
    if qa_type == "single_choice":
        return 1.0 if len(gold) == 1 and len(pred) == 1 and gold[0] == pred[0] else 0.0
    if qa_type == "multi_select":
        return 1.0 if bool(gold) and set(gold) == set(pred) and len(pred) == len(set(pred)) else 0.0
    if qa_type == "ordering":
        return 1.0 if bool(gold) and gold == pred else 0.0
    raise ValueError(f"unsupported qa_type: {qa_type}")


class ScriptMemCalculator(MetricCalculator):
    """ScriptMem：single/multi/ordering 精确字母匹配 accuracy。"""

    name: ClassVar[str] = "scriptmem"
    kind: ClassVar[MetricKind] = "benchmark"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        qas = data.get("qa") or []
        by_type: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        n = 0
        for idx, qa in enumerate(qas):
            if not isinstance(qa, dict):
                continue
            n += 1
            query = str(qa.get("question") or "")
            qa_type = str(qa.get("qa_type") or "single_choice")
            gold = [str(x) for x in (qa.get("answer_letters") or gold_letters(qa.get("answer", "")))]
            pred_text = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred_text:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred_text = outputs[idx].output
            pred, malformed = predicted_letters(pred_text, qa_type)
            score = score_item(qa_type, gold, pred, malformed)
            by_type.setdefault(qa_type, []).append(score)
            details.append(
                {
                    "idx": idx,
                    "qa_type": qa_type,
                    "gold": gold,
                    "predicted": pred,
                    "malformed": malformed,
                    "score": score,
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
