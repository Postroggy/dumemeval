"""HaluMem 数据集适配（操作级幻觉，三阶段）。

数据：官方完整数据在 HF（IAAR-Shanghai/HaluMem）；本地只有 stage5 中间产物
（dialogue + memory_points 标注），stage6（extracted_memories/questions）缺失。
组织：每个 user → 一个 EvalTask（session 1 注入对话，session 2..N 逐题回答）
指标：integrity recall / interference accuracy / update 分类 / QA 分类
⚠️ 完整三阶段评测需用户提供 HF 格式数据（含 extracted_memories/questions）。

Source: https://huggingface.co/datasets/IAAR-Shanghai/HaluMem
Code: https://github.com/MemTensor/HaluMem · Paper: https://arxiv.org/abs/2511.03506
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class HaluMemMemory(BaseModel):
    index: int = 0
    memory_content: str = ""
    memory_type: str = ""
    memory_source: str = ""
    is_update: str = "False"
    importance: float = 1.0
    timestamp: str = ""


class HaluMemQA(BaseModel):
    question: str = ""
    answer: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class HaluMemUser(BaseModel):
    uuid: str = ""
    dialogue: str = ""
    memory_points: list[HaluMemMemory] = Field(default_factory=list)
    updates: list[HaluMemMemory] = Field(default_factory=list)
    qa: list[HaluMemQA] = Field(default_factory=list)


class HaluMemData(BenchmarkData):
    users: list[HaluMemUser] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> HaluMemData:
        users: list[HaluMemUser] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            sessions = item.get("sessions") or []
            # 汇总所有 session 的 dialogue + memory_points + questions
            dialogue_parts: list[str] = []
            memory_points: list[HaluMemMemory] = []
            updates: list[HaluMemMemory] = []
            qa_list: list[HaluMemQA] = []
            for session in sessions:
                if not isinstance(session, dict):
                    continue
                dialogue = session.get("dialogue") or []
                for turn in dialogue:
                    if isinstance(turn, dict):
                        role = turn.get("role", "")
                        content = turn.get("content", "")
                        dialogue_parts.append(f"{role}: {content}")
                for mp in session.get("memory_points") or []:
                    if isinstance(mp, dict):
                        memory_points.append(HaluMemMemory.model_validate(mp))
                        if str(mp.get("is_update", "False")) == "True":
                            updates.append(HaluMemMemory.model_validate(mp))
                for q in session.get("questions") or []:
                    if isinstance(q, dict):
                        qa_list.append(
                            HaluMemQA(
                                question=str(q.get("question", "")),
                                answer=str(q.get("answer", "")),
                                evidence=list(q.get("evidence", []) or []),
                            )
                        )
            users.append(
                HaluMemUser(
                    uuid=str(item.get("uuid", "")),
                    dialogue="\n".join(dialogue_parts),
                    memory_points=memory_points,
                    updates=updates,
                    qa=qa_list,
                )
            )
        return cls(users=users)

    @staticmethod
    def load_jsonl(path: str | Path) -> HaluMemData:
        rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        return HaluMemData.from_raw(rows)


@register_benchmark
class HaluMemAdapter(BenchmarkAdapter):
    name = "halumem"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return HaluMemData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, HaluMemData):
            raise TypeError(f"Expected HaluMemData, got {type(data)}")
        tasks: list[EvalTask] = []
        for idx, user in enumerate(data.users):
            if not user.dialogue and not user.qa:
                continue
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"请阅读并记住以下用户对话（后续评测需要提取记忆并回答问题）：\n\n{user.dialogue}",
                    memory_inject=True,
                )
            ]
            for i, q in enumerate(user.qa, start=2):
                sessions.append(
                    SessionSpec(id=i, instruction=q.question, memory_inject=True, query=q.question)
                )
            tasks.append(
                EvalTask(
                    name=f"halumem_{user.uuid or idx}",
                    description=f"HaluMem {user.uuid or idx}",
                    sessions=sessions,
                    data={
                        "dialogue": user.dialogue,
                        "memory_points": [m.model_dump() for m in user.memory_points],
                        "updates": [m.model_dump() for m in user.updates],
                        "qa": [q.model_dump() for q in user.qa],
                    },
                    benchmark="halumem",
                )
            )
        return tasks
