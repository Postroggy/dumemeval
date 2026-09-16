"""跨 run 比较：接 memory vs 不接 / 多 backend 横评。

纯函数层：只读已落盘的 ``summary.json`` + ``experiment_config.json``，
不触发任何执行。有 baseline → 出 Δ；无 baseline → 只排名（leaderboard）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import (
    MetricDelta,
    MetricDirection,
    RunComparison,
    RunProvenance,
    RunRef,
    RunSummary,
)

# 越低越好的指标（后缀/子串匹配；社区加指标时在此登记）
_LOWER_IS_BETTER = (
    "cost_usd",
    "_latency_ms",
    "hallucination_rate",
    "omission_rate",
    "error_rate",
    "empty_output_rate",
    "tokens_in",
    "tokens_out",
)

# Minimum evidence for every completed run, independent of the benchmark.
# Legacy reports remain readable, but absent fields cannot establish comparability.
_REQUIRED_CONTROLS = frozenset(
    (
        "tasks",
        "dataset",
        "agent",
        "agent_skills",
        "judge",
        "runtime",
        "task_environment",
        "code",
        "observed_prompts",
    )
)


def direction_of(metric: str) -> MetricDirection:
    """按指标名判定方向（cost/latency/幻觉/错误率等越低越好）。"""
    if any(marker in metric for marker in _LOWER_IS_BETTER):
        return MetricDirection.LOWER_IS_BETTER
    return MetricDirection.HIGHER_IS_BETTER


def load_run(path: str | Path, label: str | None = None) -> RunRef:
    """读取一个 run 目录（需含 summary.json）。"""
    run_dir = Path(path)
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"{run_dir} 缺少 summary.json（先跑一次评测再 compare）")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        isinstance(payload.get("benchmark"), dict)
        and "benchmark" not in payload["benchmark"]
        and "name" in payload["benchmark"]
    ):
        payload["benchmark"]["benchmark"] = payload["benchmark"].pop("name")
    summary = RunSummary.model_validate(payload)

    provenance: RunProvenance | None = None
    config_path = run_dir / "experiment_config.json"
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw.get("provenance"), dict):
                provenance = RunProvenance.model_validate(raw["provenance"])
        except (json.JSONDecodeError, ValueError):
            provenance = None

    return RunRef(
        label=label or run_dir.name,
        path=run_dir,
        summary=summary,
        provenance=provenance,
    )


def compare_runs(runs: list[RunRef], baseline: str | None = None) -> RunComparison:
    """对齐多个 run 的指标，产出 delta / 排名 + 可比性警告。"""
    if len(runs) < 2:
        raise ValueError("compare requires at least 2 runs")
    labels = [ref.label for ref in runs]
    if len(set(labels)) != len(labels):
        raise ValueError(f"run label 重复：{labels}；请用不同目录名或显式 label")
    if baseline is not None and baseline not in labels:
        raise ValueError(f"unknown baseline {baseline!r}; available: {labels}")

    metric_names: list[str] = []
    for ref in runs:
        for name in _metrics_of(ref):
            if name not in metric_names:
                metric_names.append(name)

    deltas = [
        MetricDelta(
            metric=name,
            direction=direction_of(name),
            values={ref.label: _metrics_of(ref).get(name) for ref in runs},
            baseline=baseline,
        )
        for name in sorted(metric_names)
    ]

    return RunComparison(
        labels=labels,
        baseline=baseline,
        deltas=deltas,
        warnings=comparability_warnings(runs),
        has_mock=any(_is_mock(ref) for ref in runs),
    )


def comparability_warnings(runs: list[RunRef]) -> list[str]:
    """控制变量不一致时显式警告（业务据此判断这张表能不能引用）。"""
    warnings: list[str] = []

    fingerprints = [ref.provenance.controls if ref.provenance else {} for ref in runs]
    for ref, fields in zip(runs, fingerprints, strict=True):
        missing = sorted(key for key in _REQUIRED_CONTROLS if not fields.get(key, "").strip())
        if missing:
            warnings.append(
                f"Required control fingerprints are missing for {ref.label}: {', '.join(missing)}; "
                "experiment comparability is unverified"
            )
    if any("not-observed" in fields.values() for fields in fingerprints):
        warnings.append(
            "Actual agent/environment/prompt/skill evidence is missing; runtime comparability is unverified"
        )
    if any("not-controlled" in fields.values() for fields in fingerprints):
        warnings.append("Upstream environment randomness is not controlled; seed equivalence is unverified")
    if all(fingerprints):
        keys = set().union(*(set(fields) for fields in fingerprints))
        for key in sorted(keys):
            if len({fields.get(key) for fields in fingerprints}) > 1:
                warnings.append(
                    f"Controlled input differs: {key}; this comparison is not a controlled ablation"
                )
    if any(task.execution_status != "completed" for ref in runs for task in ref.summary.per_task):
        warnings.append("Incomplete executions are present; missing measurements cannot be treated as zero")

    mocked = [ref.label for ref in runs if _is_mock(ref)]
    if mocked:
        warnings.append(f"mock run 参与比较（{', '.join(mocked)}）：整表不可引用为实验结果")

    benchmarks = {ref.summary.benchmark.benchmark for ref in runs if ref.summary.benchmark is not None}
    if len(benchmarks) > 1:
        warnings.append(f"benchmark 不一致（{', '.join(sorted(benchmarks))}）：官方口径不可跨数据集比较")

    judges = {ref.provenance.judging_model for ref in runs if ref.provenance is not None}
    if len(judges) > 1:
        rendered = ", ".join(sorted(str(model) for model in judges))
        warnings.append(f"judge 模型不一致（{rendered}）：LLM 判分分数不可直接比较")

    task_counts = {ref.summary.n_tasks for ref in runs}
    if len(task_counts) > 1:
        rendered = ", ".join(str(count) for count in sorted(task_counts))
        warnings.append(f"task 数不一致（{rendered}）：样本量不同，差值可能来自数据而非系统")

    return warnings


def _metrics_of(ref: RunRef) -> dict[str, float]:
    """run 级扁平指标：summary.metrics 优先，缺失时从 benchmark / 平均值兜底。"""
    if ref.summary.metrics:
        return ref.summary.metrics
    fallback: dict[str, float] = {}
    if ref.summary.benchmark is not None:
        name = ref.summary.benchmark.benchmark
        for key, value in ref.summary.benchmark.values.items():
            fallback[f"{name}.{key}"] = value
    fallback["utility.success_rate"] = ref.summary.utility_success_rate_avg
    if ref.summary.quality_recall_avg is not None:
        fallback["quality.recall"] = ref.summary.quality_recall_avg
    if ref.summary.quality_precision_avg is not None:
        fallback["quality.precision"] = ref.summary.quality_precision_avg
    return fallback


def _is_mock(ref: RunRef) -> bool:
    if ref.provenance is not None:
        return ref.provenance.mock
    return ref.summary.mock
