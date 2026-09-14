"""整批汇总落盘：summary.md + summary.json。"""

from __future__ import annotations

import json
from pathlib import Path

from ..artifacts.provenance import provenance_markdown
from ..models import RunProvenance, RunSummary

__all__ = ["write_summary"]


def write_summary(
    summary: RunSummary,
    output_dir: str | Path,
    provenance: RunProvenance | None = None,
    formats: str = "json+md",
) -> None:
    """落盘整批汇总（CLI 打印之外的可留存产物）。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    payload = summary.model_dump()
    if provenance is not None:
        payload["provenance"] = provenance.model_dump()
    if formats in ("json", "json+md"):
        (out / "summary.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
    if formats in ("md", "json+md"):
        (out / "summary.md").write_text(_render_markdown(summary, provenance), encoding="utf-8")


def _render_markdown(summary: RunSummary, provenance: RunProvenance | None) -> str:
    lines = [
        f"# DuMemEval 汇总 — {summary.experiment_name or '(unnamed)'}",
        "",
        f"> {summary.generated_at} · {summary.n_tasks} tasks · 并行度 {summary.n_concurrent}",
        "",
    ]
    if provenance is not None:
        lines += provenance_markdown(provenance)
    lines += _benchmark_section(summary)
    lines += _averages_section(summary)
    lines += _per_task_section(summary)
    if summary.warnings:
        lines += ["", "## Warnings", ""]
        lines += [f"- {item}" for item in summary.warnings]
    return "\n".join(lines) + "\n"


def _benchmark_section(summary: RunSummary) -> list[str]:
    if summary.benchmark is None:
        return []
    lines = [
        f"## Benchmark[{summary.benchmark.benchmark}]（pooled，官方口径）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
    ]
    for key, value in summary.benchmark.values.items():
        lines.append(f"| {key} | {value:.4f} |")
    if summary.benchmark.by_category:
        lines += ["", "### By category", "", "| category | 指标 | 值 |", "|---|---|---|"]
        for cat, vals in summary.benchmark.by_category.items():
            for key, value in vals.items():
                lines.append(f"| {cat} | {key} | {value:.4f} |")
    lines.append("")
    return lines


def _averages_section(summary: RunSummary) -> list[str]:
    quality = (
        f"recall={summary.quality_recall_avg:.3f} precision={summary.quality_precision_avg:.3f}"
        if summary.quality_recall_avg is not None
        else "n/a（未配 ground truth）"
    )
    return [
        "## 跨 task 平均",
        "",
        f"- Quality: {quality}",
        f"- Utility: success_rate={summary.utility_success_rate_avg:.3f}",
        "",
    ]


def _per_task_section(summary: RunSummary) -> list[str]:
    lines = ["## Per-task", "", "| task | sessions | benchmark | 报告 |", "|---|---|---|---|"]
    for task in summary.per_task:
        bench = f"{task.benchmark_f1:.3f}" if task.benchmark_f1 is not None else "-"
        lines.append(
            f"| {task.task_name} | {task.n_success}/{task.n_sessions} | {bench} | `{task.report_dir}` |"
        )
    return lines
