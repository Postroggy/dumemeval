"""MemoryArena progressive_search：相互依赖的多回合搜索。

数据：Dataset/data/MemoryArena/progressive_search/data.jsonl
官方指标：GRADER_TEMPLATE + parse_judge_response → accuracy（无判定计错）。
session instruction 使用 questions 原文。

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


class SearchSample(BaseModel):
    id: int = 0
    questions: list[JsonValue] = Field(default_factory=list)
    answers: list[JsonValue] = Field(default_factory=list)


class MemoryArenaSearchData(BenchmarkData):
    samples: list[SearchSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoryArenaSearchData:
        samples = [SearchSample.model_validate(item) for item in raw]
        validate_ids([sample.id for sample in samples])
        for sample in samples:
            validate_rounds(sample.questions, sample.answers)
        return cls(samples=samples)


@register_benchmark
class MemoryArenaSearchAdapter(BenchmarkAdapter):
    name = "memoryarena_search"

    def __init__(self, judge: Callable[[str, str, str], bool] | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoryArenaSearchData

    def build_tasks(
        self, data: BenchmarkData, subset: int | None = None, max_questions: int | None = None
    ) -> list[EvalTask]:
        if not isinstance(data, MemoryArenaSearchData):
            raise TypeError(f"Expected MemoryArenaSearchData, got {type(data)}")
        tasks: list[EvalTask] = []
        for item in take(data.samples, subset):
            questions = take(item.questions, max_questions)
            answers = take(item.answers, max_questions)
            if not questions:
                continue
            sessions = [
                SessionSpec(id=i + 1, instruction=query_text(q), memory_inject=True, query=query_text(q))
                for i, q in enumerate(questions)
            ]
            tasks.append(
                EvalTask(
                    name=f"memoryarena_search_{item.id}",
                    description=f"MemoryArena progressive_search {item.id}",
                    sessions=sessions,
                    data={
                        "sample_id": item.id,
                        "source_round_count": len(item.questions),
                        "questions": questions,
                        "answers": answers,
                    },
                    benchmark="memoryarena_search",
                )
            )
        return tasks
