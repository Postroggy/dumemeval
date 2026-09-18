"""MemoryArena formal reasoning（math / phys）。

数据：
- Dataset/data/MemoryArena/formal_reasoning_math/data.jsonl
- Dataset/data/MemoryArena/formal_reasoning_phys/data.jsonl

官方指标：math_env.judge → is_correct（yes/no 数学等价）。phys 共用同一 judge。
每个 subtask 的 instruction = 该条 backgrounds + questions 原文（数据集字段，不是另造题面）。

Source: https://github.com/ZexueHe/MemoryArena · Paper: https://arxiv.org/abs/2602.16313
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, JsonValue

from dumemeval.datasets.benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark
from dumemeval.datasets.benchmarks._common import query_text
from dumemeval.models import EvalTask, SessionSpec

from ._validation import take, validate_ids, validate_rounds


class ReasoningSample(BaseModel):
    id: int = 0
    paper_name: str = ""
    questions: list[JsonValue] = Field(default_factory=list)
    answers: list[JsonValue] = Field(default_factory=list)
    backgrounds: list[JsonValue] = Field(default_factory=list)


class MemoryArenaReasoningData(BenchmarkData):
    samples: list[ReasoningSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoryArenaReasoningData:
        samples = [ReasoningSample.model_validate(item) for item in raw]
        validate_ids([sample.id for sample in samples])
        for sample in samples:
            validate_rounds(sample.questions, sample.answers)
            if len(sample.backgrounds) != len(sample.questions):
                raise ValueError("MemoryArena reasoning backgrounds must align with questions")
        return cls(samples=samples)


def _instruction(question: Any, background: Any) -> str:
    q = query_text(question)
    bg = background if isinstance(background, str) else (str(background) if background else "")
    if bg.strip():
        return f"{bg.strip()}\n\n{q}"
    return q


class _FormalReasoningAdapter(BenchmarkAdapter):
    def __init__(self, judge: Callable[[str, str, str], bool] | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoryArenaReasoningData

    def build_tasks(
        self, data: BenchmarkData, subset: int | None = None, max_questions: int | None = None
    ) -> list[EvalTask]:
        if not isinstance(data, MemoryArenaReasoningData):
            raise TypeError(f"Expected MemoryArenaReasoningData, got {type(data)}")
        tasks: list[EvalTask] = []
        for item in take(data.samples, subset):
            questions = take(item.questions, max_questions)
            answers = take(item.answers, max_questions)
            backgrounds = take(item.backgrounds, max_questions)
            if not questions:
                continue
            sessions: list[SessionSpec] = []
            for i, q in enumerate(questions):
                bg = backgrounds[i]
                sessions.append(
                    SessionSpec(
                        id=i + 1,
                        instruction=_instruction(q, bg),
                        memory_inject=True,
                        query=query_text(q),
                    )
                )
            tasks.append(
                EvalTask(
                    name=f"{self.name}_{item.id}",
                    description=f"{self.name} paper={item.paper_name}",
                    sessions=sessions,
                    data={
                        "sample_id": item.id,
                        "source_round_count": len(item.questions),
                        "questions": questions,
                        "answers": answers,
                        "backgrounds": backgrounds,
                        "paper_name": item.paper_name,
                    },
                    benchmark=self.name,
                )
            )
        return tasks


@register_benchmark
class MemoryArenaMathAdapter(_FormalReasoningAdapter):
    name = "memoryarena_math"


@register_benchmark
class MemoryArenaPhysAdapter(_FormalReasoningAdapter):
    name = "memoryarena_phys"
