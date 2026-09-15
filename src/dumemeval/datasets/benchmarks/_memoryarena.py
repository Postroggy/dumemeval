"""Shared validation, not shared prompts, for the five MemoryArena scenarios.

Source: https://huggingface.co/datasets/ZexueHe/memoryarena
"""

from collections.abc import Sequence
from typing import Any

from ._common import query_text


def validate_rounds(questions: Sequence[Any], answers: Sequence[Any]) -> None:
    """Reject silent truncation and unscorable rounds before starting an agent."""
    if len(questions) != len(answers):
        raise ValueError("MemoryArena questions and answers must have equal lengths")
    if any(not query_text(question).strip() for question in questions):
        raise ValueError("MemoryArena questions must not be empty")


def validate_ids(ids: Sequence[int]) -> None:
    """Task identifiers also namespace memory, so collisions must be rejected."""
    if len(ids) != len(set(ids)):
        raise ValueError("MemoryArena sample ids must be unique")


def take[T](items: list[T], limit: int | None) -> list[T]:
    """Deterministic prefix selection, with explicit rejection of invalid limits."""
    if limit is not None and (isinstance(limit, bool) or limit < 1):
        raise ValueError("MemoryArena subset/max_questions must be a positive integer")
    return items[:limit] if limit is not None else items
