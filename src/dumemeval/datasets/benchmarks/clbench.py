"""CL-bench / CL-bench-Life 数据集适配（Context Learning）。

数据：Dataset/data/CL-bench/CL-bench.jsonl + "CL-bench Life.jsonl"
组织：每条样本 = context（messages）+ rubrics → 一个 EvalTask：
  - session 1：注入 context 文本（记忆）
  - session 2：回答问题（LLM judge 按 rubrics 全有或全无打分）
指标：solving_rate（官方 eval.py）

Source: https://huggingface.co/datasets/tencent/CL-bench
Paper: https://arxiv.org/abs/2602.03587
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class CLBenchSample(BaseModel):
    id: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    rubrics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def context_text(self) -> str:
        parts = []
        for msg in self.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}" if role else str(content))
        return "\n".join(parts)

    @property
    def question(self) -> str:
        # 最后一个 user 消息即问题
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return str(msg.get("content", ""))
        return ""

    @property
    def context_category(self) -> str:
        return str(self.metadata.get("context_category", ""))


class CLBenchData(BenchmarkData):
    samples: list[CLBenchSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> CLBenchData:
        return cls(samples=[CLBenchSample.model_validate(item) for item in raw or []])

    @staticmethod
    def load_jsonl(path: str | Path) -> CLBenchData:
        """加载 jsonl，跳过解析失败的行（官方数据含少量损坏行）。"""
        rows: list[dict[str, Any]] = []
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return CLBenchData.from_raw(rows)


@register_benchmark
class CLBenchAdapter(BenchmarkAdapter):
    name = "clbench"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return CLBenchData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, CLBenchData):
            raise TypeError(f"Expected CLBenchData, got {type(data)}")
        tasks: list[EvalTask] = []
        for idx, sample in enumerate(data.samples):
            if not sample.question:
                continue
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"请阅读并记住以下上下文，后续任务需要基于它完成：\n\n{sample.context_text}",
                    memory_inject=True,
                ),
                SessionSpec(
                    id=2,
                    instruction=sample.question,
                    memory_inject=True,
                    query=sample.question,
                ),
            ]
            tasks.append(
                EvalTask(
                    name=f"clbench_{idx}",
                    description=f"CL-bench {sample.context_category} #{idx}",
                    sessions=sessions,
                    data={
                        "samples": [
                            {
                                "question": sample.question,
                                "rubrics": sample.rubrics,
                                "context_category": sample.context_category,
                            }
                        ]
                    },
                    benchmark="clbench",
                )
            )
        return tasks
