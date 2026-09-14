"""BEAM 数据集适配（长上下文记忆问答，10 类）。

数据：Dataset/benchmarks/conversation/BEAM/aml_input_beam.jsonl（400 题，10 类 × 40）
组织：每题 → 一个 EvalTask（session 1 注入 context，session 2 回答问题）
指标：llm_judge_score（官方 rubric 打分）

Source: https://huggingface.co/datasets/Mohammadta/BEAM （10M 版：Mohammadta/BEAM-10M）
Paper: https://arxiv.org/pdf/2510.27246
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class BeamSample(BaseModel):
    id: str = ""
    question: str = ""
    context: str = ""
    rubrics: list[str] = Field(default_factory=list)
    question_type: str = ""
    ideal_response: str = ""
    difficulty: str = ""
    topic_id: str = ""
    chat_size: str = ""


class BeamData(BenchmarkData):
    samples: list[BeamSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> BeamData:
        return cls(samples=[BeamSample.model_validate(item) for item in raw or []])

    @staticmethod
    def load_jsonl(path: str | Path) -> BeamData:
        rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        return BeamData.from_raw(rows)


@register_benchmark
class BeamAdapter(BenchmarkAdapter):
    name = "beam"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return BeamData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, BeamData):
            raise TypeError(f"Expected BeamData, got {type(data)}")
        tasks: list[EvalTask] = []
        for sample in data.samples:
            if not sample.question:
                continue
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"请阅读并记住以下对话记录，后续问题需要基于它回答：\n\n{sample.context}",
                    memory_inject=True,
                ),
                SessionSpec(id=2, instruction=sample.question, memory_inject=True, query=sample.question),
            ]
            tasks.append(
                EvalTask(
                    name=f"beam_{sample.id}",
                    description=f"BEAM {sample.question_type} {sample.id}",
                    sessions=sessions,
                    data={
                        "samples": [
                            {
                                "question": sample.question,
                                "rubrics": sample.rubrics,
                                "question_type": sample.question_type,
                            }
                        ]
                    },
                    benchmark="beam",
                )
            )
        return tasks
