"""EverMemBench-Dynamic 数据集适配（多人群聊记忆）。

数据：Dataset/data/EverMemBench-Dynamic/{01..05}/（dialogue.json + qa_XX.json）
组织：每个 topic → 一个 EvalTask：
  - session 1：注入该 topic 的完整群聊对话（记忆）
  - session 2..N：每题一个 session（MC：只输出字母；OE：输出答案）
指标：accuracy（MC 规则 / OE LLM judge），按 MC/OE + id 前缀分桶

Source: https://github.com/EverMind-AI/EverMemBench-Static （Dynamic 同系列）
Paper: https://arxiv.org/abs/2602.01313
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class EverMemQA(BaseModel):
    topic_id: str = ""
    id: str = ""
    question: str = ""
    answer: str = ""
    reference: list[dict[str, Any]] = Field(default_factory=list)
    options: dict[str, str] | None = None

    @property
    def mode(self) -> str:
        return "multiple_choice" if self.options else "open_ended"


class EverMemTopic(BaseModel):
    topic_id: str = ""
    dialogues: str = ""  # 完整群聊文本（注入用）
    qa: list[EverMemQA] = Field(default_factory=list)


class EverMemBenchDynamicData(BenchmarkData):
    topics: list[EverMemTopic] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> EverMemBenchDynamicData:
        """raw: list[dict{topic_id, dialogues, qa:[{...}]}]。"""
        topics: list[EverMemTopic] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            topics.append(
                EverMemTopic(
                    topic_id=str(item.get("topic_id", "")),
                    dialogues=str(item.get("dialogues", "")),
                    qa=[EverMemQA.model_validate(q) for q in item.get("qa", []) if isinstance(q, dict)],
                )
            )
        return cls(topics=topics)

    @classmethod
    def load_dir(cls, data_dir: str | Path) -> EverMemBenchDynamicData:
        """从 0X/qa_XX.json + 0X/dialogue.json 加载。"""
        root = Path(data_dir)
        topics: list[EverMemTopic] = []
        for qa_path in sorted(root.glob("*/qa_*.json")):
            topic_id = qa_path.parent.name
            questions = json.loads(qa_path.read_text())
            # 群聊文本：dialogue.json 是 [{"date", "dialogues": {group: [msgs]}}]
            dialogue_path = qa_path.parent / "dialogue.json"
            dialogue_text = ""
            if dialogue_path.exists():
                parts = []
                for day in json.loads(dialogue_path.read_text()):
                    day_dialogues = day.get("dialogues", {}) if isinstance(day, dict) else {}
                    for group, msgs in day_dialogues.items():
                        for msg in msgs or []:
                            if isinstance(msg, dict):
                                speaker = msg.get("speaker", "")
                                text = msg.get("dialogue", "")
                                parts.append(f"[{day.get('date', '')}][{group}][{speaker}] {text}")
                dialogue_text = "\n".join(parts)
            topics.append(
                EverMemTopic(
                    topic_id=topic_id,
                    dialogues=dialogue_text,
                    qa=[
                        EverMemQA(
                            topic_id=topic_id,
                            id=str(q.get("id", "")),
                            question=str(q.get("Q", "")),
                            answer=str(q.get("A", "")),
                            reference=list(q.get("R", []) or []),
                            options=dict(q["options"]) if isinstance(q.get("options"), dict) else None,
                        )
                        for q in questions
                        if isinstance(q, dict)
                    ],
                )
            )
        return cls(topics=topics)


@register_benchmark
class EverMemBenchDynamicAdapter(BenchmarkAdapter):
    name = "evermembench_dynamic"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return EverMemBenchDynamicData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, EverMemBenchDynamicData):
            raise TypeError(f"Expected EverMemBenchDynamicData, got {type(data)}")
        tasks: list[EvalTask] = []
        for topic in data.topics:
            if not topic.qa:
                continue
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"请阅读并记住以下多人群聊记录，后续问题需要基于它回答：\n\n{topic.dialogues}",
                    memory_inject=True,
                )
            ]
            for i, q in enumerate(topic.qa, start=2):
                prompt = q.question
                if q.options:
                    opts = "\n".join(f"{k}. {v}" for k, v in q.options.items())
                    prompt = f"{q.question}\n\n选项：\n{opts}\n（只输出选项字母 A/B/C/D）"
                sessions.append(SessionSpec(id=i, instruction=prompt, memory_inject=True, query=prompt))
            tasks.append(
                EvalTask(
                    name=f"evermembench_dynamic_{topic.topic_id}",
                    description=f"EverMemBench-Dynamic topic {topic.topic_id}（{len(topic.qa)} 题）",
                    sessions=sessions,
                    data={
                        "questions": [
                            {
                                "id": q.id,
                                "question": (
                                    f"{q.question}\n\n选项：\n"
                                    + "\n".join(f"{k}. {v}" for k, v in q.options.items())
                                    + "\n（只输出选项字母 A/B/C/D）"
                                    if q.options
                                    else q.question
                                ),
                                "answer": q.answer,
                                "options": q.options,
                            }
                            for q in topic.qa
                        ]
                    },
                    benchmark="evermembench_dynamic",
                )
            )
        return tasks
