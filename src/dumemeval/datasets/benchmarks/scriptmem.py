"""ScriptMem 数据集适配（确定性 MCQ：single/multi/ordering）。

数据：Dataset/benchmarks/conversation/ScriptMem/data/public/questions.jsonl
（官方导出，含 answer_letters；raw 的 angry.json 剧本文本因版权未发布）

组织：按 conversation_id 分组 → 一个 EvalTask（每个问题一个 session）。
官方无 memory 语料可注入（版权），评测即"问答"。

Source: https://github.com/memorax-ai/ScriptMem
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.scriptmem import gold_letters
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class ScriptMemQA(BaseModel):
    qa_id: str = ""
    question_id: str = ""
    conversation_id: str = ""
    source: str = ""
    sample_id: str = ""
    qa_index: int = 0
    qa_type: str = "single_choice"
    question: str = ""
    option: list[str] = Field(default_factory=list)
    answer: Any = ""
    answer_letters: list[str] = Field(default_factory=list)


class ScriptMemData(BenchmarkData):
    qa: list[ScriptMemQA] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> ScriptMemData:
        return cls(qa=[ScriptMemQA.model_validate(item) for item in raw])


@register_benchmark
class ScriptMemAdapter(BenchmarkAdapter):
    name = "scriptmem"

    @property
    def data_type(self) -> type[BenchmarkData]:
        return ScriptMemData

    @staticmethod
    def load_jsonl(path: str | Path) -> ScriptMemData:
        rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        return ScriptMemData.from_raw(rows)

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, ScriptMemData):
            raise TypeError(f"Expected ScriptMemData, got {type(data)}")
        by_conv: dict[str, list[ScriptMemQA]] = {}
        for qa in data.qa:
            by_conv.setdefault(qa.conversation_id or "scriptmem", []).append(qa)

        tasks: list[EvalTask] = []
        for conv_id, qas in by_conv.items():
            if not qas:
                continue
            sessions = [
                SessionSpec(
                    id=i + 1,
                    instruction=q.question,
                    memory_inject=True,
                    query=q.question,
                )
                for i, q in enumerate(qas)
            ]
            tasks.append(
                EvalTask(
                    name=f"scriptmem_{conv_id}",
                    description=f"ScriptMem {conv_id}（{len(qas)} 题）",
                    sessions=sessions,
                    data={
                        "qa": [
                            {
                                "question": q.question,
                                "qa_type": q.qa_type,
                                "answer": q.answer,
                                "answer_letters": q.answer_letters or gold_letters(q.answer),
                            }
                            for q in qas
                        ]
                    },
                    benchmark="scriptmem",
                )
            )
        return tasks
