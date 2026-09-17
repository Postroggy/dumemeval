"""MemoryArena progressive_search 官方指标。

来源：
- env/env_systems/web_search_env/search_agent/prompts.py ``GRADER_TEMPLATE``
  （模板在 ``verifier/prompts.py`` SEARCH_GRADER_JUDGE_PROMPT，输出字段解析在
  ``verifier/parsers.py`` parse_judge_response——见 verifier 判分体系）
- run_search.py：accuracy = 判定为 correct 的比例；无 judgement 计为不正确（计入分母）

本任务的 answers 是检索答案文本，不是 ASIN，也不是 travel daily_plans。
不把 shopping/travel 指标套过来。recall 依赖 qrel/doc id，本地 jsonl 无该字段则不报 recall。

无显式 judge 注入时（真实评测场景），懒加载 ``LLMJudgeVerifier``
（``prompt="search_grader"``，即上面这套官方 GRADER_TEMPLATE）做真实判分，
而不是把"没配 judge"和"judge 判定为 no"混为一谈——之前的实现里两者都直接
返回 ``correct=False, parse_error=True``，导致真实评测下 accuracy 恒为 0。
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind, round_items
from .locomo import JudgeFn


class MemoryArenaSearchCalculator(MetricCalculator):
    """progressive_search：官方 accuracy（unevaluated 计错）。"""

    name: ClassVar[str] = "memoryarena_search"
    kind: ClassVar[MetricKind] = "benchmark"
    metrics: ClassVar[tuple[str, ...]] = ("is_correct",)

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        flags: list[float] = []
        confidences: list[float] = []
        details: list[dict[str, Any]] = []
        n = 0
        for idx, _question, query, gold, pred in round_items(inp):
            n += 1
            gold_text = gold if isinstance(gold, str) else str(gold)
            parsed = self._judge_one(pred, gold_text, query)
            correct = bool(parsed.get("correct"))
            flags.append(1.0 if correct else 0.0)
            if parsed.get("confidence") is not None:
                confidences.append(float(parsed["confidence"]))
            details.append(
                {
                    "round_idx": idx,
                    "query": query,
                    "correct": correct,
                    "parse_error": parsed.get("parse_error", False),
                    "confidence": parsed.get("confidence"),
                }
            )

        values: dict[str, float] = {"accuracy": sum(flags) / n if n else 0.0}
        if confidences:
            values["confidence"] = sum(confidences) / len(confidences)
        return MetricBundle(name=self.name, kind=self.kind, values=values, details=details)

    def _judge_one(self, pred: str, gold: str, question: str) -> dict[str, Any]:
        if self._judge is not None:
            ok = bool(self._judge(pred, gold, question))
            # 官方规则：无 confidence 可用时记 100（不随 correct 翻转伪造置信度）
            return {"correct": ok, "parse_error": False, "confidence": 100.0}
        if not pred:
            return {"correct": False, "parse_error": True, "confidence": None}
        if self._llm is None:
            from ...verifier import make_llm_judge

            self._llm = make_llm_judge("search_grader", self._llm_config)
        verdict = self._llm.verify(pred, gold, question=question)
        return {
            "correct": verdict.is_pass,
            "parse_error": False,
            "confidence": 100.0 if verdict.is_pass else 0.0,
        }
