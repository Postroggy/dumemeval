"""MemoryArena formal reasoning（math / phys）。

数据：
- Dataset/data/MemoryArena/formal_reasoning_math/data.jsonl
- Dataset/data/MemoryArena/formal_reasoning_phys/data.jsonl

官方指标：math_env.judge → is_correct（yes/no 数学等价）。phys 共用同一 judge。
每个 subtask 的 instruction = 该条 backgrounds + questions 原文（数据集字段，不是另造题面）。

Source: https://github.com/ZexueHe/MemoryArena · Paper: https://arxiv.org/abs/2602.16313
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark
from ._common import query_text


class ReasoningSample(BaseModel):
    id: int = 0
    paper_name: str = ""
    questions: list[Any] = Field(default_factory=list)
    answers: list[Any] = Field(default_factory=list)
    backgrounds: list[Any] = Field(default_factory=list)


class MemoryArenaReasoningData(BenchmarkData):
    samples: list[ReasoningSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoryArenaReasoningData:
        return cls(samples=[ReasoningSample.model_validate(item) for item in raw])


def _instruction(question: Any, background: Any) -> str:
    q = query_text(question)
    bg = background if isinstance(background, str) else (str(background) if background else "")
    if bg.strip():
        return f"{bg.strip()}\n\n{q}"
    return q


class _FormalReasoningAdapter(BenchmarkAdapter):
    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoryArenaReasoningData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, MemoryArenaReasoningData):
            raise TypeError(f"Expected MemoryArenaReasoningData, got {type(data)}")
        tasks: list[EvalTask] = []
        for item in data.samples:
            if not item.questions:
                continue
            sessions: list[SessionSpec] = []
            for i, q in enumerate(item.questions):
                bg = item.backgrounds[i] if i < len(item.backgrounds) else ""
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
                        "questions": [query_text(q) for q in item.questions],
                        "answers": item.answers,
                        "backgrounds": item.backgrounds,
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
