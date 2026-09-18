"""MemoryArena travel 数据集适配（agent multi-turn memory）。

数据来源 MemoryArena group_travel_planner：
- 每个样本 = base_person（初始记忆）+ 8 个 interdependent questions
- 指标：官方 slot 相似度（metrics.benchmarks.memoryarena）+ judgement_mode hint/answer
- 适配器只负责 build_tasks；evaluate 委托统一指标层

Source: https://github.com/ZexueHe/MemoryArena · Paper: https://arxiv.org/abs/2602.16313
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue

from dumemeval.datasets.benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark
from dumemeval.models import EvalTask, MemoryFact, SessionSpec

from ._validation import take, validate_ids, validate_rounds

JudgementMode = Literal["hint", "answer", "none"]


class TravelQuestion(BaseModel):
    """MemoryArena travel 单个回合问题。"""

    round_idx: int = 0
    name: str = ""
    query: str = ""


class TravelSample(BaseModel):
    """MemoryArena travel 单个样本（base_person + rounds）。"""

    id: int = 0
    base_person: dict[str, JsonValue] = Field(default_factory=dict)
    questions: list[TravelQuestion] = Field(default_factory=list)
    answers: list[JsonValue] = Field(default_factory=list)


class MemoryArenaTravelData(BenchmarkData):
    """MemoryArena travel 类型化数据。"""

    samples: list[TravelSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoryArenaTravelData:
        samples: list[TravelSample] = []
        for item in raw:
            questions = item.get("questions", [])
            validate_rounds(questions, item.get("answers", []))
            parsed_qs = [
                TravelQuestion(
                    round_idx=q.get("round_idx", i + 1) if isinstance(q, dict) else i + 1,
                    name=q.get("name", "Person") if isinstance(q, dict) else _person_name(q),
                    query=q if isinstance(q, str) else q.get("query", ""),
                )
                for i, q in enumerate(questions)
            ]
            validate_ids([q.round_idx for q in parsed_qs])
            samples.append(
                TravelSample(
                    id=item.get("id", 0),
                    base_person=item.get("base_person") or {},
                    questions=parsed_qs,
                    answers=_align_answers(parsed_qs, item.get("answers", [])),
                )
            )
        validate_ids([sample.id for sample in samples])
        return cls(samples=samples)


@register_benchmark
class MemoryArenaTravelAdapter(BenchmarkAdapter):
    """MemoryArena travel：agent multi-turn 规划 + 跨回合记忆。"""

    name = "memoryarena_travel"

    def __init__(self, judgement_mode: JudgementMode = "hint"):
        self.judgement_mode: JudgementMode = judgement_mode

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoryArenaTravelData

    def build_tasks(
        self,
        data: BenchmarkData,
        subset: int | None = None,
        max_questions: int | None = None,
        judgement_mode: JudgementMode | None = None,
    ) -> list[EvalTask]:
        """每个样本 → 一个 multi-session EvalTask（round 间有依赖）。"""
        if not isinstance(data, MemoryArenaTravelData):
            raise TypeError(f"Expected MemoryArenaTravelData, got {type(data)}")
        if judgement_mode in ("hint", "answer", "none"):
            self.judgement_mode = judgement_mode

        tasks: list[EvalTask] = []
        samples = take(data.samples, subset)
        for item in samples:
            base_person = item.base_person
            questions = take(item.questions, max_questions)
            answers = take(item.answers, max_questions)
            if not questions:
                continue

            sessions: list[SessionSpec] = []

            if base_person:
                base_text = f"旅行者：{base_person.get('name', '')}\n需求：{base_person.get('query', '')}"
                base_text += f"\n基础行程：\n{_json_dumps(base_person.get('daily_plans', []))}"
                sessions.append(
                    SessionSpec(
                        id=1,
                        instruction=f"记住以下旅行者的长期偏好和计划，后续规划时应用：\n\n{base_text}",
                        memory_inject=True,
                    )
                )

            for round_idx, q in enumerate(questions):
                sessions.append(
                    SessionSpec(
                        id=len(sessions) + 1,
                        instruction=(
                            f"这是第 {round_idx + 1} 个规划回合。请根据你记住的旅行者偏好"
                            f"（包括之前的回合信息）完成这个规划请求：\n\n{q.query}\n\n"
                            f"输出格式：=== {q.name}'s Plan ===，随后逐日列出 Day N: 和行程槽位。"
                        ),
                        memory_inject=True,
                        query=q.query,
                    )
                )

            facts: list[MemoryFact] = []
            bp_query_raw = base_person.get("query", "")
            bp_query = bp_query_raw if isinstance(bp_query_raw, str) else ""
            for line in bp_query.splitlines():
                line = line.strip()
                if line and len(line) > 5 and not line.startswith("I am"):
                    facts.append(MemoryFact(fact=line, category="persona"))

            task = EvalTask(
                name=f"memoryarena_travel_{item.id}",
                description=f"MemoryArena travel group {item.id}",
                sessions=sessions,
                memory_ground_truth="\n".join(f.fact for f in facts),
                task_ground_truth=_json_dumps(answers),
                data={
                    "sample_id": item.id,
                    "source_round_count": len(item.questions),
                    "questions": [q.model_dump() for q in questions],
                    "answers": answers,
                    "base_person": base_person,
                    "judgement_mode": self.judgement_mode,
                },
                benchmark="memoryarena_travel",
            )
            tasks.append(task)
        return tasks


def _person_name(query: str) -> str:
    match = re.match(r"I am (\w+)\.", query)
    return match.group(1) if match else "Person"


def _align_answers(questions: list[TravelQuestion], answers: list[Any]) -> list[Any]:
    indexed = [answer for answer in answers if isinstance(answer, dict) and "round_idx" in answer]
    if not indexed:
        return answers
    if len(indexed) != len(answers):
        raise ValueError("Travel answers cannot mix indexed and unindexed rounds")
    by_round = {answer["round_idx"]: answer for answer in indexed}
    if len(by_round) != len(answers) or set(by_round) != {q.round_idx for q in questions}:
        raise ValueError("Travel answer round_idx values must match question round_idx values")
    return [by_round[q.round_idx] for q in questions]


def _json_dumps(obj: Any) -> str:
    import json

    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False)
