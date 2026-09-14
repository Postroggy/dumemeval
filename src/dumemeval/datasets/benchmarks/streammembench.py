"""StreamMemBench：流式观察 → 首答 →（按需修改）→ follow-up。

数据：Dataset/benchmarks/conversation/StreamMemBench/data/
官方四指标：fidelity / initial_evidence_use / feedback_incorporation / followup_reuse
（docs/evaluation.md；确定性路径见 DeterministicUserFeedbackSimulator）。

Agent 侧 instruction 只用 stream_segment 与 user_request，
不把 evidence_statement / expected_behavior 泄漏进 session（官方禁止）。
这两项只进入 task.data 供评测器使用。

Source: https://github.com/landian60/StreamMemBench
Paper: https://arxiv.org/abs/2606.14571
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class StreamMemBenchItem(BaseModel):
    participant: str = ""
    day: str = ""
    segment_id: int | str = 0
    time_range: str = ""
    stream_segment: dict[str, Any] = Field(default_factory=dict)
    evidence_anchors: list[dict[str, Any]] = Field(default_factory=list)


class StreamMemBenchData(BenchmarkData):
    items: list[StreamMemBenchItem] = Field(default_factory=list)
    language: str = "zh"

    @classmethod
    def from_raw(cls, raw: Any) -> StreamMemBenchData:
        language = "zh"
        rows: list[Any]
        if isinstance(raw, dict):
            language = str(raw.get("language") or raw.get("lang") or "zh")
            rows = raw.get("items") or []
        else:
            rows = list(raw)
        return cls(
            language=language,
            items=[StreamMemBenchItem.model_validate(item) for item in rows],
        )


@register_benchmark
class StreamMemBenchAdapter(BenchmarkAdapter):
    name = "streammembench"

    def __init__(self, lang: str = "zh"):
        self.lang = lang

    @property
    def data_type(self) -> type[BenchmarkData]:
        return StreamMemBenchData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, StreamMemBenchData):
            raise TypeError(f"Expected StreamMemBenchData, got {type(data)}")
        lang = data.language or self.lang
        tasks: list[EvalTask] = []
        for item in data.items:
            stream_text = ""
            if isinstance(item.stream_segment, dict):
                stream_text = str(item.stream_segment.get("text") or "")
            for anchor in item.evidence_anchors:
                if not isinstance(anchor, dict):
                    continue
                tasks_spec = anchor.get("tasks") or {}
                initial = tasks_spec.get("initial_task") or {}
                followup = tasks_spec.get("followup_task") or {}
                initial_req = str(initial.get("user_request") or "")
                followup_req = str(followup.get("user_request") or "")
                if not initial_req or not followup_req:
                    continue
                sessions = [
                    SessionSpec(id=1, instruction=stream_text, memory_inject=True),
                    SessionSpec(id=2, instruction=initial_req, memory_inject=True, query=initial_req),
                    SessionSpec(id=3, instruction=followup_req, memory_inject=True, query=followup_req),
                ]
                eid = str(anchor.get("evidence_id") or f"{item.participant}-{item.segment_id}")
                tasks.append(
                    EvalTask(
                        name=f"streammembench_{item.participant}_{item.day}_{eid}",
                        description=f"StreamMemBench {item.participant} {item.day} {eid}",
                        sessions=sessions,
                        data={
                            "language": lang,
                            "participant": item.participant,
                            "day": item.day,
                            "segment_id": item.segment_id,
                            "evidence_id": eid,
                            "evidence_statement": str(anchor.get("evidence_statement") or ""),
                            "stream_text": stream_text,
                            "initial_user_request": initial_req,
                            "followup_user_request": followup_req,
                            "initial_expected_behavior": str(initial.get("expected_behavior") or ""),
                            "followup_expected_behavior": str(followup.get("expected_behavior") or ""),
                            "questions": [
                                {"query": initial_req},
                                {"query": followup_req},
                            ],
                        },
                        benchmark="streammembench",
                    )
                )
        return tasks
