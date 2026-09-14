"""Memora 数据集适配（遗忘感知 FAMA）。

数据：Dataset/benchmarks/conversation/Memora/data/{weekly,monthly,quarterly}/<persona>/
组织：每题 → 一个 EvalTask（session 1 注入记忆，session 2 回答主问题）
指标：fama（+ mpa/faa/λ 明细），按 task（remembering/reasoning/recommending）分桶

Paper: https://arxiv.org/abs/2604.20006
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...metrics.benchmarks.memora import fama_score
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class MemoraSubQuestion(BaseModel):
    evaluation_question_id: str = ""
    evaluation_question: str = ""
    expected_answer: str = ""
    evaluation_type: str = ""


class MemoraQuestion(BaseModel):
    question_id: str = ""
    question: str = ""
    question_date: str = ""
    memory_evidence: dict[str, Any] = Field(default_factory=dict)
    forgetting_evidence: dict[str, Any] = Field(default_factory=dict)
    evaluation: list[MemoraSubQuestion] = Field(default_factory=list)
    task: str = ""
    persona: str = ""
    period: str = ""


class MemoraData(BenchmarkData):
    questions: list[MemoraQuestion] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoraData:
        questions: list[MemoraQuestion] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            eval_raw = item.get("evaluation") or {}
            raw_subs = eval_raw.get("evaluation_questions") if isinstance(eval_raw, dict) else []
            subs: list[Any] = list(raw_subs) if raw_subs else []
            questions.append(
                MemoraQuestion(
                    question_id=str(item.get("question_id", "")),
                    question=str(item.get("question", "")),
                    question_date=str(item.get("question_date", "")),
                    memory_evidence=item.get("memory_evidence") or {},
                    forgetting_evidence=item.get("forgetting_evidence") or {},
                    evaluation=[MemoraSubQuestion.model_validate(s) for s in subs if isinstance(s, dict)],
                    task=str(item.get("task", "unknown")),
                    persona=str(item.get("persona", "")),
                    period=str(item.get("period", "")),
                )
            )
        return cls(questions=questions)

    @staticmethod
    def load_period_dir(root: str | Path, period: str, personas: list[str] | None = None) -> MemoraData:
        """从 <root>/<period>/<persona>/evaluation_questions_*.json 加载。"""
        base = Path(root) / period
        questions: list[dict[str, Any]] = []
        if not base.exists():
            return MemoraData(questions=[])
        for qfile in sorted(base.glob("*/evaluation_questions_*.json")):
            persona = qfile.parent.name
            if personas and persona not in personas:
                continue
            data = json.loads(qfile.read_text())
            for task, qs in (data.get("questions") or {}).items():
                for q in qs:
                    q = dict(q)
                    q["task"] = task
                    q["persona"] = persona
                    q["period"] = period
                    questions.append(q)
        return MemoraData.from_raw(questions)


@register_benchmark
class MemoraAdapter(BenchmarkAdapter):
    name = "memora"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoraData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, MemoraData):
            raise TypeError(f"Expected MemoraData, got {type(data)}")
        tasks: list[EvalTask] = []
        for q in data.questions:
            if not q.question:
                continue
            # 记忆：session 文件由用户注入（本 adapter 以 memory_evidence 提示）
            evidence_text = "（该问题的记忆来自用户历史会话，由评测环境注入）"
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"以下是用户的历史会话记忆背景：\n\n{evidence_text}",
                    memory_inject=True,
                ),
                SessionSpec(id=2, instruction=q.question, memory_inject=True, query=q.question),
            ]
            tasks.append(
                EvalTask(
                    name=f"memora_{q.period}_{q.persona}_{q.question_id}",
                    description=f"Memora {q.period}/{q.persona} {q.task} {q.question_id}",
                    sessions=sessions,
                    data={
                        "questions": [
                            {
                                "question": q.question,
                                "task": q.task,
                                "evaluation": {
                                    "evaluation_questions": [s.model_dump() for s in q.evaluation]
                                },
                            }
                        ]
                    },
                    benchmark="memora",
                )
            )
        return tasks


__all__ = ["MemoraAdapter", "MemoraData", "MemoraQuestion", "fama_score"]
