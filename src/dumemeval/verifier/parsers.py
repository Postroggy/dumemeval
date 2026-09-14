"""LLM judge 输出解析（纯函数）：yes/no、search grader 字段、JSON/裸 label。

从 LLMJudgeVerifier 拆出（无状态），便于独立测试与复用。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import Verdict


def parse_yes_no(raw: str) -> Verdict:
    """math_equivalence 专用：官方 prompt 只回答 "yes"/"no"（无 JSON/label）。"""
    text = raw.strip().lower()
    ok = "yes" in text
    return Verdict(label="yes" if ok else "no", score=1.0 if ok else 0.0, reason=raw[:200], raw=raw)


def parse_judge_response(judge_response: str) -> dict[str, Any]:
    """官方 evaluate_with_openai.parse_judge_response（search_grader 输出字段提取）。"""
    result: dict[str, Any] = {
        "extracted_final_answer": None,
        "reasoning": None,
        "correct": None,
        "confidence": None,
        "parse_error": False,
    }
    if not judge_response:
        result["parse_error"] = True
        return result

    answer_match = re.search(
        r"\*\*extracted_final_answer:\*\*\s*(.*?)(?=\n|$)",
        judge_response,
        re.IGNORECASE | re.DOTALL,
    ) or re.search(
        r"extracted_final_answer:\s*(.*?)(?=\n|$)",
        judge_response,
        re.IGNORECASE | re.DOTALL,
    )
    if answer_match:
        result["extracted_final_answer"] = answer_match.group(1).strip()

    correct_match = re.search(r"\*\*correct:\*\*\s*(yes|no)", judge_response, re.IGNORECASE) or re.search(
        r"correct:\s*(yes|no)", judge_response, re.IGNORECASE
    )
    if correct_match:
        result["correct"] = correct_match.group(1).lower() == "yes"

    confidence_match = re.search(
        r"\*\*confidence:\*\*\s*(\d+(?:\.\d+)?)\s*%?", judge_response, re.IGNORECASE
    ) or re.search(r"confidence:\s*(\d+(?:\.\d+)?)\s*%?", judge_response, re.IGNORECASE)
    if confidence_match:
        result["confidence"] = min(float(confidence_match.group(1)), 100.0)

    reasoning_match = re.search(
        r"\*\*reasoning:\*\*\s*(.*?)(?=\n\*\*correct|\ncorrect:|$)",
        judge_response,
        re.IGNORECASE | re.DOTALL,
    ) or re.search(
        r"reasoning:\s*(.*?)(?=\n\*\*correct|\ncorrect:|$)",
        judge_response,
        re.IGNORECASE | re.DOTALL,
    )
    if reasoning_match:
        result["reasoning"] = reasoning_match.group(1).strip()

    if result["correct"] is None:
        result["parse_error"] = True
    return result


def parse_search_grader(raw: str) -> Verdict:
    """search_grader 专用：解析官方 GRADER_TEMPLATE 的 ``correct: yes/no`` 字段。"""
    parsed = parse_judge_response(raw)
    ok = bool(parsed.get("correct"))
    return Verdict(
        label="yes" if ok else "no",
        score=1.0 if ok else 0.0,
        reason=str(parsed.get("reasoning") or "")[:200],
        raw=raw,
    )


def parse(raw: str) -> Verdict:
    """解析 judge 输出（JSON 或裸 label）。"""
    raw = raw.strip()
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            score = float(
                data.get(
                    "score",
                    1.0 if data.get("label") in ("CORRECT", "pass") else 0.0,
                )
            )
            label = data.get("label", "pass" if score >= 0.5 else "fail")
            return Verdict(label=label, score=score, reason=data.get("reason", ""), raw=raw)
        except (json.JSONDecodeError, ValueError):
            pass
    if "CORRECT" in raw.upper():
        return Verdict(label="CORRECT", score=1.0, reason=raw[:200], raw=raw)
    if "WRONG" in raw.upper():
        return Verdict(label="WRONG", score=0.0, reason=raw[:200], raw=raw)
    return Verdict(label="UNKNOWN", score=0.0, reason=raw[:200], raw=raw)
