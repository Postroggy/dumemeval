"""Locomo-Plus 数据集适配（认知记忆/语义断层）。

数据：Dataset/benchmarks/conversation/Locomo-Plus/data/locomo_plus.json
官方流程（evaluation_framework/）：unified_input.py 把 cue/query 缝合进 locomo10
对话并按 6 类（multi-hop/temporal/common-sense/single-hop/adversarial/Cognitive）
定类别，然后 evaluate.sh 拿 prediction、judge.sh 用 6 类 LLM-judge 模板判分
（correct=1/partial=0.5/wrong=0，Cognitive 无 gold 判 awareness）。

本地只有 locomo_plus.json（cue_dialogue/trigger_query/time_gap/relation_type），
缝合后的 unified 数据未随仓库提供。adapter 用 relation_type（causal/state/goal/value）
作为类别分桶，并将 cue_dialogue 作为 evidence 注入、trigger_query 作为问题。
指标：score（LLM judge 评分）按类别聚合。

⚠️ 注意：官方 judge 是 LLM，无注入 judge 时懒加载 LLMJudgeVerifier 用官方模板
真实判分；测试注入 judge 隔离。

Source: https://github.com/snap-research/LoCoMo （Plus 扩展）
Paper: https://arxiv.org/abs/2602.10715
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class LocomoPlusSample(BaseModel):
    """locomo_plus.json 单条：cue/trigger 对。"""

    relation_type: str = ""
    cue_dialogue: str = ""
    trigger_query: str = ""
    time_gap: str = ""
    model_name: str = ""
    scores: dict[str, float] = Field(default_factory=dict)
    ranks: dict[str, int] = Field(default_factory=dict)
    final_similarity_score: float = 0.0
    answer: str = ""  # 缝合后才有（本地缺失）


class LocomoPlusData(BenchmarkData):
    samples: list[LocomoPlusSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> LocomoPlusData:
        return cls(samples=[LocomoPlusSample.model_validate(item) for item in raw])

    @staticmethod
    def load_json(path: str | Path) -> LocomoPlusData:
        return LocomoPlusData.from_raw(json.loads(Path(path).read_text()))


@register_benchmark
class LocomoPlusAdapter(BenchmarkAdapter):
    name = "locomo_plus"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return LocomoPlusData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, LocomoPlusData):
            raise TypeError(f"Expected LocomoPlusData, got {type(data)}")
        tasks: list[EvalTask] = []
        for idx, sample in enumerate(data.samples):
            if not sample.trigger_query:
                continue
            # cue 作为记忆注入（用户早期说过的话），trigger 作为当前问题
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"以下是用户早前的一段对话（{sample.time_gap} 前）：\n\n{sample.cue_dialogue}",
                    memory_inject=True,
                ),
                SessionSpec(
                    id=2,
                    instruction=sample.trigger_query,
                    memory_inject=True,
                    query=sample.trigger_query,
                ),
            ]
            tasks.append(
                EvalTask(
                    name=f"locomo_plus_{idx}",
                    description=f"Locomo-Plus {sample.relation_type} #{idx}",
                    sessions=sessions,
                    data={
                        "samples": [
                            {
                                "trigger_query": sample.trigger_query,
                                "cue_dialogue": sample.cue_dialogue,
                                "answer": sample.answer,
                                "category": sample.relation_type,
                            }
                        ]
                    },
                    benchmark="locomo_plus",
                )
            )
        return tasks
