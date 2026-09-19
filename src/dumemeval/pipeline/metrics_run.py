"""指标计算：per-task 四维 + benchmark、pooled 聚合、run 级扁平指标。

只依赖 metrics / models——不碰报告落盘（那是 summary.py 的事）。
"""

from __future__ import annotations

from collections.abc import Callable

from ..metrics.core.registry import calculator_names, get_benchmark_calculator
from ..models import BenchmarkResult, EvalTask, RunSummary, TaskResult

RuleJudge = Callable[[str, str, str], bool]

__all__ = ["pool_benchmark", "run_metrics"]


def pool_benchmark(results: list[BenchmarkResult], warnings: list[str]) -> BenchmarkResult:
    """Aggregate official benchmark results; aggregation policy is explicit here."""
    if not results:
        raise ValueError("cannot aggregate empty benchmark results")
    name = results[0].benchmark
    if any(r.benchmark != name for r in results):
        raise ValueError("cannot aggregate different benchmarks in one run")
    if len({r.score_scope for r in results}) != 1:
        warnings.append("Official and derived measurements cannot be pooled together")
        return BenchmarkResult(benchmark=name, score_scope="derived", coverage_note=warnings[-1])
    coverage = " ".join(dict.fromkeys(r.coverage_note for r in results if r.coverage_note))
    if coverage:
        warnings.append(coverage)
    if name in calculator_names():
        official = get_benchmark_calculator(name).aggregate(results)
        if official is not None:
            official = official.model_copy(
                update={
                    "score_scope": results[0].score_scope,
                    "coverage_note": coverage or official.coverage_note,
                }
            )
            if not official.values:
                warnings.append("Official aggregate is unmeasured: incomplete evidence or truncated tasks")
            return official
    details = [d for r in results for d in r.details]
    if details and all("f1" in d for d in details):
        values = {
            "f1": sum(float(d["f1"]) for d in details) / len(details),
            "accuracy": sum(float(bool(d.get("correct"))) for d in details) / len(details),
        }
        by_category: dict[str, dict[str, float]] = {}
        for detail in details:
            category = str(detail.get("category_name") or detail.get("category") or "default")
            totals = by_category.setdefault(category, {"f1": 0.0, "accuracy": 0.0, "count": 0.0})
            totals["f1"] += float(detail["f1"])
            totals["accuracy"] += float(bool(detail.get("correct")))
            totals["count"] += 1
        for category, totals in by_category.items():
            totals["f1"] /= totals["count"]
            totals["accuracy"] /= totals["count"]
            values[f"f1_{category}"] = totals["f1"]
            values[f"accuracy_{category}"] = totals["accuracy"]
        return BenchmarkResult(
            benchmark=name,
            score_scope=results[0].score_scope,
            coverage_note=coverage,
            primary_metric="f1",
            values=values,
            by_category=by_category,
            details=details,
        )
    warnings.append(f"benchmark {name} 无 per-QA 明细，pooled 值退化为 task 间平均")
    keys = set.intersection(*(set(r.values) for r in results))
    if any(set(r.values) != keys for r in results):
        warnings.append("Incomplete benchmark measurements: unavailable metrics remain unmeasured")
    return BenchmarkResult(
        benchmark=name,
        score_scope=results[0].score_scope,
        coverage_note=coverage,
        primary_metric=results[0].primary_metric,
        values={k: sum(r.values.get(k, 0.0) for r in results) / len(results) for k in keys},
        details=details,
    )


def run_metrics(summary: RunSummary, results: list[TaskResult]) -> dict[str, float]:
    """run 级扁平指标（``dumemeval compare`` 直接 diff 这里）。

    - benchmark：pooled 官方口径（``<bench>.<metric>``）
    - quality / utility / efficiency / trace：跨 task 平均（缺失维度不写，保持「未测 ≠ 0」）
    """
    metrics: dict[str, float] = {}
    if summary.benchmark is not None:
        name = summary.benchmark.benchmark
        for key, value in summary.benchmark.values.items():
            metrics[f"{name}.{key}"] = value

    n = len(results)
    if not n:
        return metrics

    if summary.quality_recall_avg is not None:
        metrics["quality.recall"] = summary.quality_recall_avg
    if summary.quality_precision_avg is not None:
        metrics["quality.precision"] = summary.quality_precision_avg
    metrics["utility.success_rate"] = summary.utility_success_rate_avg
    utility = [r.metrics.utility for r in results if r.metrics and r.metrics.utility]
    efficiency = [r.metrics.efficiency for r in results if r.metrics and r.metrics.efficiency]
    if utility:
        metrics["utility.turns"] = sum(r.turns for r in utility) / len(utility)
    if efficiency:
        metrics["efficiency.tokens_in"] = sum(r.tokens_in for r in efficiency) / len(efficiency)
        metrics["efficiency.tokens_out"] = sum(r.tokens_out for r in efficiency) / len(efficiency)
        metrics["efficiency.cost_usd"] = sum(r.cost_usd for r in efficiency) / len(efficiency)

    traced = [r.metrics.trace for r in results if r.metrics is not None and r.metrics.trace is not None]
    if traced:
        count = len(traced)
        metrics["trace.trace_captured_rate"] = sum(t.trace_captured_rate for t in traced) / count
        metrics["trace.empty_output_rate"] = sum(t.empty_output_rate for t in traced) / count
        metrics["trace.error_rate"] = sum(t.error_rate for t in traced) / count
        measured = [t for t in traced if t.memory_tool_used is not None]
        metrics["trace.memory_observation_coverage"] = len(measured) / count
        if measured:
            metrics["trace.memory_tool_used_rate"] = sum(bool(t.memory_tool_used) for t in measured) / len(
                measured
            )
    return metrics


def _benchmark_options(task: EvalTask) -> dict[str, str]:
    mode, lang = "hint", "zh"
    if isinstance(task.data, dict):
        if task.data.get("judgement_mode"):
            mode = str(task.data["judgement_mode"])
        if task.data.get("language"):
            lang = str(task.data["language"])
    return {"judgement_mode": mode, "lang": lang}
