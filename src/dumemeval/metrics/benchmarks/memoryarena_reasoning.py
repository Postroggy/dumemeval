"""MemoryArena formal_reasoning_math / formal_reasoning_phys 官方指标。

来源：env/env_systems/math_env.py ``judge``（phys 共用同一环境）：
- 官方 prompt：判断两个表达式是否数学等价，只回答 yes/no
- 官方解析：``"yes" in output.lower()``
- run_math.py 记录字段名：``is_correct``

不把该任务映射成 travel 的 round_success / slot 相似度，也不复用 memory_qa prompt。

无显式 judge 注入时（真实评测场景），懒加载 ``LLMJudgeVerifier``
（``prompt="math_equivalence"``，即上面这条官方 yes/no prompt）做真实判分，
而不是静默返回 False——那样会让每次真实评测的 is_correct 恒为 0，
且没有任何提示。仅测试可通过注入 judge 跳过真实 LLM 调用。
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind, round_items
from .locomo import JudgeFn

MATH_JUDGE_SYSTEM = "You are a helpful assistant that judges the equivalence of two mathematical expressions."

MATH_JUDGE_PROMPT = """
            You are a math expert.
            Determine if these two expressions are mathematically equivalent answer for the given question:
            Question: {query}
            Expression 1: {action}
            Expression 2: {ground_truth}

            Respond only with "yes" or "no". """


def parse_math_judge_output(output: str) -> bool:
    """官方 math_env.judge：``"yes" in output.lower()``。"""
    return "yes" in (output or "").lower()


class MemoryArenaReasoningCalculator(MetricCalculator):
    """formal reasoning：官方 is_correct。name 由 math/phys 子类区分。"""

    kind: ClassVar[MetricKind] = "benchmark"
    name: ClassVar[str] = "memoryarena_math"
    metrics: ClassVar[tuple[str, ...]] = ("is_correct",)

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        flags: list[float] = []
        details: list[dict[str, Any]] = []
        n = 0
        for idx, _question, query, gold, pred in round_items(inp):
            n += 1
            gold_text = gold if isinstance(gold, str) else str(gold)
            correct = self._is_correct(pred, gold_text, query)
            flags.append(1.0 if correct else 0.0)
            details.append(
                {
                    "round_idx": idx,
                    "query": query,
                    "is_correct": correct,
                    "predicted": pred[:300],
                }
            )

        return MetricBundle(
            name=self.name,
            kind=self.kind,
            values={"is_correct": sum(flags) / n if n else 0.0},
            details=details,
        )

    def _is_correct(self, pred: str, gold: str, question: str) -> bool:
        if self._judge is not None:
            return bool(self._judge(pred, gold, question))
        if not pred:
            return False
        if self._llm is None:
            from ...verifier import make_llm_judge

            self._llm = make_llm_judge("math_equivalence", self._llm_config)
        return bool(self._llm.verify(pred, gold, question=question).is_pass)


class MemoryArenaMathCalculator(MemoryArenaReasoningCalculator):
    name: ClassVar[str] = "memoryarena_math"


class MemoryArenaPhysCalculator(MemoryArenaReasoningCalculator):
    name: ClassVar[str] = "memoryarena_phys"
