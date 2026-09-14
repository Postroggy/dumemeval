"""MemoryBench 数据集适配（28 子集，指标异构）。

数据：Dataset/data/MemoryBench/dataset/<子集>/（HF arrow 格式，用 datasets 库读）
组织：每个子集 → 一个 EvalTask（session 1 注入 input_prompt 对话，session 2..N 逐题回答）
指标：按子集路由（Locomo F1 / DialSim exact+judge / LexEval ROUGE-L / 生成型 judge）

Source: https://huggingface.co/datasets/THUIR/MemoryBench （全量：THUIR/MemoryBench-Full）
Paper: https://arxiv.org/abs/2510.17281
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class MemoryBenchSample(BaseModel):
    test_idx: int = 0
    question: str = ""
    golden_answer: str = ""
    category: int = 0
    input_prompt: str = ""
    dataset: str = ""


class MemoryBenchData(BenchmarkData):
    samples: list[MemoryBenchSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoryBenchData:
        samples: list[MemoryBenchSample] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            info = item.get("info") or {}
            if isinstance(info, str):
                try:
                    info = json.loads(info)
                except json.JSONDecodeError:
                    info = {}
            samples.append(
                MemoryBenchSample(
                    test_idx=int(item.get("test_idx") or 0),
                    question=str(item.get("origin_question") or ""),
                    golden_answer=str(info.get("golden_answer", "") if isinstance(info, dict) else ""),
                    category=int(info.get("category", 0) if isinstance(info, dict) else 0),
                    input_prompt=str(item.get("input_prompt") or ""),
                    dataset=str(item.get("dataset_name") or ""),
                )
            )
        return cls(samples=samples)

    @staticmethod
    def load_dataset_dir(root: str | Path, subset: str) -> MemoryBenchData:
        """加载单个子集的 test split（HF arrow 格式）。"""
        from datasets import load_from_disk

        ds = load_from_disk(str(Path(root) / subset))
        split = ds.get("test") if "test" in ds else ds.get("train")
        return MemoryBenchData.from_raw(split.to_list())


@register_benchmark
class MemoryBenchAdapter(BenchmarkAdapter):
    name = "memorybench"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoryBenchData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, MemoryBenchData):
            raise TypeError(f"Expected MemoryBenchData, got {type(data)}")
        by_dataset: dict[str, list[MemoryBenchSample]] = {}
        for sample in data.samples:
            by_dataset.setdefault(sample.dataset or "unknown", []).append(sample)

        tasks: list[EvalTask] = []
        for dataset, samples in by_dataset.items():
            if not samples:
                continue
            prompt = samples[0].input_prompt or "（上下文见 input_prompt）"
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"请阅读并记住以下对话上下文，后续问题需要基于它回答：\n\n{prompt}",
                    memory_inject=True,
                )
            ]
            for i, sample in enumerate(samples, start=2):
                sessions.append(
                    SessionSpec(id=i, instruction=sample.question, memory_inject=True, query=sample.question)
                )
            tasks.append(
                EvalTask(
                    name=f"memorybench_{dataset}",
                    description=f"MemoryBench {dataset}（{len(samples)} 题）",
                    sessions=sessions,
                    data={
                        "samples": [
                            {
                                "question": sample.question,
                                "golden_answer": sample.golden_answer,
                                "category": sample.category,
                                "dataset": sample.dataset,
                            }
                            for sample in samples
                        ]
                    },
                    benchmark="memorybench",
                )
            )
        return tasks
