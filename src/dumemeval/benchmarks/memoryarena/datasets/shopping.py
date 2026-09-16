"""MemoryArena bundled_shopping：相互依赖的多回合购物。

官方链路（vendors/MemoryArena/run_shopping.py + env_client.py）：
agent 经 HTTP env server 逐步 ``search[...]`` / ``click[...]`` / ``click[Buy Now]``，
``info.last_purchased_asin`` 才是可打分的购买结果。本适配器把任务目标写成
EvalTask，并把 ``task_environment`` 指到 webshop；**不把商品目录摊进 instruction**。

官方指标：ASIN exact match（match_ground_truth）+ overall_success + attribute 字符串匹配。

Source: https://github.com/ZexueHe/MemoryArena · Paper: https://arxiv.org/abs/2602.16313
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from dumemeval.datasets.benchmark import BenchmarkAdapter, BenchmarkData
from dumemeval.datasets.benchmarks._common import query_text
from dumemeval.models import EvalTask, SessionSpec

from ._validation import take, validate_ids, validate_rounds


class ShoppingSample(BaseModel):
    id: int = 0
    questions: list[Any] = Field(default_factory=list)
    answers: list[Any] = Field(default_factory=list)
    category: str = ""


class MemoryArenaShoppingData(BenchmarkData):
    samples: list[ShoppingSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoryArenaShoppingData:
        samples = [ShoppingSample.model_validate(item) for item in raw]
        validate_ids([sample.id for sample in samples])
        for sample in samples:
            validate_rounds(sample.questions, sample.answers)
        return cls(samples=samples)


class MemoryArenaShoppingAdapter(BenchmarkAdapter):
    name = "memoryarena_shopping"

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoryArenaShoppingData

    def build_tasks(
        self, data: BenchmarkData, subset: int | None = None, max_questions: int | None = None
    ) -> list[EvalTask]:
        """samples → EvalTask 列表。

        subset:        只取前 N 个样本（smoke）。
        max_questions: 每个样本只取前 N 回合（仍须 >=2 才能过 memory_session_transfer）。
        """
        if not isinstance(data, MemoryArenaShoppingData):
            raise TypeError(f"Expected MemoryArenaShoppingData, got {type(data)}")
        tasks: list[EvalTask] = []
        samples = take(data.samples, subset)
        for item in samples:
            questions = take(item.questions, max_questions)
            answers = take(item.answers, max_questions)
            if not questions:
                continue
            sessions = [
                SessionSpec(
                    id=i + 1,
                    instruction=_shopping_instruction(query_text(q), i + 1, len(questions)),
                    memory_inject=True,
                    query=query_text(q),
                )
                for i, q in enumerate(questions)
            ]
            tasks.append(
                EvalTask(
                    name=f"memoryarena_shopping_{item.id}",
                    description=f"MemoryArena bundled_shopping {item.category or item.id}",
                    sessions=sessions,
                    data={
                        "sample_id": item.id,
                        "source_round_count": len(item.questions),
                        "questions": [query_text(q) for q in questions],
                        "answers": answers,
                        "category": item.category,
                    },
                    benchmark="memoryarena_shopping",
                    task_environment={
                        "type": "webshop",
                        "base_url": None,
                        "config": {"env_name": "webshop"},
                    },
                )
            )
        return tasks


def _shopping_instruction(goal: str, step: int, n_steps: int) -> str:
    """把官方任务目标交给 agent，并强制走 webshop 动作，而不是在文本里假装购买。"""
    return (
        f"这是 bundled_shopping 第 {step}/{n_steps} 个购买步骤。\n"
        "你必须通过任务环境（TASK_ENV_URL / WEBSHOP_ENV_URL）完成购买："
        "每回合只输出一个 search[...] 或 click[...] 动作，直到 click[Buy Now]。\n"
        "不要编造 ASIN，不要在没有 env 观测的情况下声称已购买。\n"
        "本步目标：\n\n"
        f"{goal}"
    )
