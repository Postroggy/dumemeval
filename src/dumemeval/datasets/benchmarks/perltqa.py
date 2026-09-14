"""PerLTQA 数据集适配（个人长期 QA，中英双语）。

数据：Dataset/benchmarks/conversation/PerLTQA/Dataset/{en,zh}/perltqa_*.json
组织：每个角色 → 一个 EvalTask（session 1 注入该角色记忆，session 2..N 逐题回答）
指标：EM + token F1（适配层判分，官方评测代码未发布——见 metrics/perltqa.py 注释）

Paper: https://aclanthology.org/2024.sighan-1.18/ （许可 CC BY-NC 4.0）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark

_SECTIONS = ("profile", "social_relationship", "events", "dialogues")


class PerLTQAItem(BaseModel):
    name: str = ""
    section: str = ""
    question: str = ""
    answer: str = ""
    reference_memory: Any = ""
    memory_anchors: list[dict[str, Any]] = Field(default_factory=list)


class PerLTQAData(BenchmarkData):
    items: list[PerLTQAItem] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> PerLTQAData:
        items: list[PerLTQAItem] = []
        for person in raw or []:
            if not isinstance(person, dict):
                continue
            for name, sections in person.items():
                if not isinstance(sections, dict):
                    continue
                for section, qas in sections.items():
                    if section not in _SECTIONS or not isinstance(qas, list):
                        continue
                    # profile 段是平铺 QA 列表；其余段是 [{记忆key: [QA...]}]
                    flat: list[dict[str, Any]] = []
                    for entry in qas:
                        if not isinstance(entry, dict):
                            continue
                        if "Question" in entry:
                            flat.append(entry)
                        else:
                            for qa_list in entry.values():
                                if isinstance(qa_list, list):
                                    flat.extend(x for x in qa_list if isinstance(x, dict))
                    for qa in flat:
                        items.append(
                            PerLTQAItem(
                                name=str(name),
                                section=str(section),
                                question=str(qa.get("Question", "")),
                                answer=str(qa.get("Answer", "")),
                                reference_memory=qa.get("Reference Memory", ""),
                                memory_anchors=list(qa.get("Memory Anchors", []) or []),
                            )
                        )
        return cls(items=items)

    @staticmethod
    def load_json(path: str | Path) -> PerLTQAData:
        return PerLTQAData.from_raw(json.loads(Path(path).read_text()))


@register_benchmark
class PerLTQAAdapter(BenchmarkAdapter):
    name = "perltqa"

    @property
    def data_type(self) -> type[BenchmarkData]:
        return PerLTQAData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, PerLTQAData):
            raise TypeError(f"Expected PerLTQAData, got {type(data)}")
        by_person: dict[str, list[PerLTQAItem]] = {}
        for item in data.items:
            by_person.setdefault(item.name, []).append(item)

        tasks: list[EvalTask] = []
        for name, items in by_person.items():
            if not items:
                continue
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"以下是角色 {name} 的记忆库（profile/关系/事件/对话），请记住：\n\n（记忆由评测环境注入）",
                    memory_inject=True,
                )
            ]
            for i, item in enumerate(items, start=2):
                sessions.append(
                    SessionSpec(id=i, instruction=item.question, memory_inject=True, query=item.question)
                )
            tasks.append(
                EvalTask(
                    name=f"perltqa_{name}",
                    description=f"PerLTQA {name}（{len(items)} 题）",
                    sessions=sessions,
                    data={
                        "questions": [
                            {"question": item.question, "answer": item.answer, "section": item.section}
                            for item in items
                        ]
                    },
                    benchmark="perltqa",
                )
            )
        return tasks
