"""Small helpers shared by benchmark task builders."""

from __future__ import annotations

from typing import Any


def query_text(question: Any) -> str:
    if isinstance(question, str):
        return question
    if isinstance(question, dict):
        return str(question.get("query") or question.get("question") or "")
    return str(question)
