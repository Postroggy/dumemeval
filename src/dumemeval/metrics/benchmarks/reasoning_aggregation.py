"""MemoryArena paper-weighted aggregation, including the official per-k curves.

Source: MemoryArena env/env_systems/formal_reasoning_env/eval.py.
"""

from __future__ import annotations

from ...models import BenchmarkResult


def aggregate_papers(results: list[BenchmarkResult]) -> BenchmarkResult:
    """A paper passes when its final subquery passes; progress weights papers equally."""
    name = results[0].benchmark
    details = [d for result in results for d in result.details]
    papers = [
        [bool(d["is_correct"]) for d in result.details if d.get("score_status") == "measured"]
        for result in results
    ]
    if not all(papers) or any("overall_average_passrate" not in result.values for result in results):
        return BenchmarkResult(benchmark=name, details=details)
    max_k, min_k = max(map(len, papers)), min(map(len, papers))
    correct = [sum(p[k] for p in papers if k < len(p)) for k in range(max_k)]
    counts = [sum(k < len(p) for p in papers) for k in range(max_k)]
    at_k = [c / n for c, n in zip(correct, counts, strict=True)]
    cumulative = [sum(correct[: k + 1]) / sum(counts[: k + 1]) for k in range(max_k)]
    details.append(
        {
            "aggregation": "official_paper",
            "min_k": min_k,
            "passrate_at_k": at_k,
            "cummulative_passrate_at_k": cumulative,
            "passrate_at_min_k": at_k[:min_k],
            "cummulative_passrate_at_min_k": cumulative[:min_k],
        }
    )
    return BenchmarkResult(
        benchmark=name,
        primary_metric="overall_average_passrate",
        values={
            "overall_average_passrate": sum(p[-1] for p in papers) / len(papers),
            "avg_progress_score": sum(sum(p) / len(p) for p in papers) / len(papers),
            "is_correct": sum(correct) / sum(counts),
        },
        details=details,
    )
