"""MemoryArena progressive_search 官方指标。

来源：
- env/env_systems/web_search_env/search_agent/prompts.py ``GRADER_TEMPLATE``
  （模板在 ``verifier/prompts.py`` SEARCH_GRADER_JUDGE_PROMPT，输出字段解析在
  ``verifier/parsers.py`` parse_judge_response——见 verifier 判分体系）
- run_search.py：每个 query ID 的最终综合问题判为 correct 的比例。
- browsecomp_plus_env.py::run_full：前置子问题构建 memory，仅 run_final_query 判分。

本任务的 answers 是检索答案文本，不是 ASIN，也不是 travel daily_plans。
不把 shopping/travel 指标套过来。recall 依赖 qrel/doc id，本地 jsonl 无该字段则不报 recall。

无显式 judge 注入时（真实评测场景），懒加载 ``LLMJudgeVerifier``
（``prompt="search_grader"``，即上面这套官方 GRADER_TEMPLATE）做真实判分，
而不是把"没配 judge"和"judge 判定为 no"混为一谈——之前的实现里两者都直接
返回 ``correct=False, parse_error=True``，导致真实评测下 accuracy 恒为 0。
"""

from __future__ import annotations

from typing import Any, ClassVar

from ...models import BenchmarkResult
from ..core.base import (
    MetricBundle,
    MetricCalculator,
    MetricInput,
    MetricKind,
    outcome_for_round,
    round_items,
)
from .locomo import JudgeFn


class MemoryArenaSearchCalculator(MetricCalculator):
    """progressive_search：最终综合问题的官方 accuracy。"""

    name: ClassVar[str] = "memoryarena_search"
    kind: ClassVar[MetricKind] = "benchmark"
    metrics: ClassVar[tuple[str, ...]] = ("is_correct",)

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        rounds = list(round_items(inp))
        source_count = int(inp.task.data.get("source_round_count", len(rounds)))
        detail: dict[str, Any] = {
            "sample_id": inp.task.data.get("sample_id"),
            "round_idx": source_count - 1,
            "source_round_count": source_count,
            "score_status": "not_measured",
            "official_score": None,
        }
        bundle = MetricBundle(name=self.name, kind=self.kind, details=[detail])
        detail = bundle.details[0]
        if not rounds or len(rounds) != source_count:
            detail["reason"] = "Original final combined query is absent (empty or truncated task)."
            return bundle
        idx, _question, query, gold, pred = rounds[-1]
        outcome = outcome_for_round(inp, idx)
        managed = inp.task.task_environment.get("type") == "memoryarena"
        if outcome is None or not outcome.success or (managed and outcome.environment is None):
            detail["reason"] = "Final query execution or required environment evidence is missing or failed."
            return bundle
        parsed = self._judge_one(pred, gold if isinstance(gold, str) else str(gold), query)
        if parsed.get("score_status") == "not_measured":
            detail.update(parsed)
            return bundle
        correct = bool(parsed.get("correct"))
        detail.update(
            query=query,
            correct=correct,
            parse_error=parsed.get("parse_error", False),
            confidence=parsed.get("confidence"),
            score_status="measured",
            official_score=float(correct),
            judge_observation=parsed.get("raw"),
        )
        bundle.values["accuracy"] = float(correct)
        if parsed.get("confidence") is not None:
            bundle.values["confidence"] = float(parsed["confidence"])
        return bundle

    def aggregate(self, results: list[BenchmarkResult]) -> BenchmarkResult:
        """Each complete query ID has equal weight, regardless of context length."""
        pooled = BenchmarkResult(benchmark=self.name, details=[d for r in results for d in r.details])
        if not results or any("accuracy" not in result.values for result in results):
            return pooled
        pooled.primary_metric = "accuracy"
        pooled.values["accuracy"] = sum(r.values["accuracy"] for r in results) / len(results)
        confidences = [r.values["confidence"] for r in results if "confidence" in r.values]
        if confidences:
            pooled.values["confidence"] = sum(confidences) / len(confidences)
        return pooled

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
        try:
            verdict = self._llm.verify(pred, gold, question=question)
        except Exception as exc:
            return {"score_status": "not_measured", "judge_error": f"{type(exc).__name__}: {exc}"}
        if verdict.label == "SKIPPED":
            return {"score_status": "not_measured", "judge_error": verdict.reason, "raw": verdict.raw}
        from ...verifier.parsers import parse_judge_response

        return {**parse_judge_response(verdict.raw), "raw": verdict.raw}
