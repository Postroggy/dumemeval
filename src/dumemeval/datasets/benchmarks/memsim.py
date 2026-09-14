"""memsim / MemDaily 数据集适配（6 类 4 选 1 问答）。

数据：Dataset/benchmarks/conversation/memsim/data_generation/final_dataset/memdaily.json
组织：按 (type, 场景) 分组 → 每个 trajectory 一个 EvalTask：
  - session 1：注入 message_list（记忆）
  - session 2：回答 QA（question + choices）
指标：accuracy（选项字母 exact match）+ recall@step（官方 TimeFlow.py）

Source: https://github.com/nuster1128/MemSim
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class MemSimQA(BaseModel):
    qid: str = ""
    question: str = ""
    answer: str = ""
    target_step_id: Any = ""
    choices: dict[str, str] = Field(default_factory=dict)
    ground_truth: str = ""
    time: str = ""
    type: str = ""  # simple/conditional/comparative/aggregative/post_processing/noisy


class MemSimTrajectory(BaseModel):
    tid: str = ""
    message_list: list[dict[str, Any]] = Field(default_factory=list)
    qa: MemSimQA | None = None


class MemSimData(BenchmarkData):
    trajectories: list[MemSimTrajectory] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemSimData:
        # raw 是 {type: {scene: [trajectory]}}
        trajs: list[MemSimTrajectory] = []
        for qtype, scenes in raw.items():
            if not isinstance(scenes, dict):
                continue
            for _scene, items in scenes.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    qa_raw = item.get("QA") or {}
                    trajs.append(
                        MemSimTrajectory(
                            tid=str(item.get("tid", "")),
                            message_list=list(item.get("message_list", []) or []),
                            qa=MemSimQA(
                                qid=str(qa_raw.get("qid", "")),
                                question=str(qa_raw.get("question", "")),
                                answer=str(qa_raw.get("answer", "")),
                                target_step_id=qa_raw.get("target_step_id", ""),
                                choices=_parse_choices(qa_raw.get("choices")),
                                ground_truth=str(qa_raw.get("ground_truth", "")),
                                time=str(qa_raw.get("time", "")),
                                type=str(qtype),
                            ),
                        )
                    )
        return cls(trajectories=trajs)

    @staticmethod
    def load_json(path: str | Path) -> MemSimData:
        return MemSimData.from_raw(json.loads(Path(path).read_text()))


def _parse_choices(raw: Any) -> dict[str, str]:
    """choices 是字符串化的 dict（"{'A': '本科', ...}"）。"""
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except (ValueError, SyntaxError):
            pass
    return {}


@register_benchmark
class MemSimAdapter(BenchmarkAdapter):
    name = "memsim"

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemSimData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, MemSimData):
            raise TypeError(f"Expected MemSimData, got {type(data)}")
        tasks: list[EvalTask] = []
        for traj in data.trajectories:
            qa = traj.qa
            if qa is None or not qa.question:
                continue
            memory_text = "\n".join(
                f"[{m.get('mid', '')}] {m.get('time', '')} {m.get('place', '')}: {m.get('message', '')}"
                for m in traj.message_list
            )
            choices_text = "\n".join(f"{k}. {v}" for k, v in qa.choices.items())
            question_text = f"{qa.question}\n\n选项：\n{choices_text}"
            tasks.append(
                EvalTask(
                    name=f"memsim_{traj.tid}",
                    description=f"MemDaily {qa.type} {traj.tid}",
                    sessions=[
                        SessionSpec(id=1, instruction=memory_text, memory_inject=True),
                        SessionSpec(
                            id=2,
                            instruction=f"请基于记住的信息回答以下问题（只输出选项字母 A/B/C/D）：\n\n{question_text}",
                            memory_inject=True,
                            query=question_text,
                        ),
                    ],
                    data={
                        "qa": [
                            {
                                "question": question_text,
                                "ground_truth": qa.ground_truth,
                                "target_step_id": qa.target_step_id,
                                "type": qa.type,
                                "answer": qa.answer,
                            }
                        ]
                    },
                    benchmark="memsim",
                )
            )
        return tasks
