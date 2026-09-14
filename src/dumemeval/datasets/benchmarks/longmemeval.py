"""LongMemEval 数据集适配（ICLR 2025）。

数据：Dataset/data/longmemeval_data/2_questions/0822_all_500_questions_final_v2.json
组织：每个问题 → 一个 EvalTask：
  - session 1：注入该题的证据句（facts）作为记忆
  - session 2：回答问题
指标：accuracy（LLM judge，5 类模板 + abstention）+ abstention_accuracy
      （question_id 以 _abs 结尾的题单独计分，不计入 overall）

Source: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned
Code: https://github.com/xiaowu0162/LongMemEval-V2 · Paper: https://arxiv.org/pdf/2410.10813.pdf
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class LongMemEvalQuestion(BaseModel):
    question_id: str = ""
    background_id: str = ""
    question_type: str = ""
    question_content: dict[str, Any] = Field(default_factory=dict)
    sessions: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def question_text(self) -> str:
        return str(self.question_content.get("question", ""))

    @property
    def answer(self) -> str:
        return str(self.question_content.get("answer", ""))

    @property
    def facts(self) -> list[str]:
        facts = self.question_content.get("facts", [])
        return [str(f) for f in facts] if isinstance(facts, list) else []

    @property
    def abstention(self) -> bool:
        return str(self.question_id).endswith("_abs")


class LongMemEvalData(BenchmarkData):
    questions: list[LongMemEvalQuestion] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> LongMemEvalData:
        return cls(questions=[LongMemEvalQuestion.model_validate(q) for q in raw or []])

    @staticmethod
    def load_json(path: str | Path) -> LongMemEvalData:
        return LongMemEvalData.from_raw(json.loads(Path(path).read_text()))


@register_benchmark
class LongMemEvalAdapter(BenchmarkAdapter):
    name = "longmemeval"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return LongMemEvalData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, LongMemEvalData):
            raise TypeError(f"Expected LongMemEvalData, got {type(data)}")
        tasks: list[EvalTask] = []
        for q in data.questions:
            if not q.question_text:
                continue
            evidence_text = "\n".join(q.facts) or "（无证据句）"
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"以下是用户过去说过/发生过的相关事实，请记住：\n\n{evidence_text}",
                    memory_inject=True,
                ),
                SessionSpec(
                    id=2,
                    instruction=q.question_text,
                    memory_inject=True,
                    query=q.question_text,
                ),
            ]
            tasks.append(
                EvalTask(
                    name=f"longmemeval_{q.question_id}",
                    description=f"LongMemEval {q.question_type} {q.question_id}",
                    sessions=sessions,
                    data={
                        "questions": [
                            {
                                "question": q.question_text,
                                "answer": q.answer,
                                "question_id": q.question_id,
                                "question_type": q.question_type,
                            }
                        ]
                    },
                    benchmark="longmemeval",
                )
            )
        return tasks
