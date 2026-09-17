"""MemoryArena progressive_search：相互依赖的多回合搜索。

数据：Dataset/data/MemoryArena/progressive_search/data.jsonl
官方指标：GRADER_TEMPLATE + parse_judge_response → accuracy（无判定计错）。
session instruction 使用 questions 原文。

Source: https://github.com/ZexueHe/MemoryArena · Paper: https://arxiv.org/abs/2602.16313
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, JsonValue

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark
from ._common import query_text


class SearchSample(BaseModel):
    id: int = 0
    questions: list[JsonValue] = Field(default_factory=list)
    answers: list[JsonValue] = Field(default_factory=list)


class MemoryArenaSearchData(BenchmarkData):
    samples: list[SearchSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoryArenaSearchData:
        return cls(samples=[SearchSample.model_validate(item) for item in raw])


@register_benchmark
class MemoryArenaSearchAdapter(BenchmarkAdapter):
    name = "memoryarena_search"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoryArenaSearchData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, MemoryArenaSearchData):
            raise TypeError(f"Expected MemoryArenaSearchData, got {type(data)}")
        tasks: list[EvalTask] = []
        for item in data.samples:
            if not item.questions:
                continue
            sessions = [
                SessionSpec(id=i + 1, instruction=query_text(q), memory_inject=True, query=query_text(q))
                for i, q in enumerate(item.questions)
            ]
            tasks.append(
                EvalTask(
                    name=f"memoryarena_search_{item.id}",
                    description=f"MemoryArena progressive_search {item.id}",
                    sessions=sessions,
                    data={
                        "questions": [query_text(q) for q in item.questions],
                        "answers": item.answers,
                    },
                    benchmark="memoryarena_search",
                )
            )
        return tasks
