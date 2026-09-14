"""跨 run 比较报告渲染（compare 的 Markdown / JSON 产出）。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import MetricDelta, RunComparison, RunRef

_ARROW = {True: "↑", False: "↓"}


def render_markdown(comparison: RunComparison, runs: list[RunRef]) -> str:
    """一张 metric × run 表：有 baseline 出 Δ 列，无 baseline 标 best。"""
    baseline = comparison.baseline
    title = "对比（vs baseline）" if baseline else "横评（无 baseline）"
    lines = [f"# DuMemEval {title}", ""]
    lines.append("> " + " · ".join(f"{ref.label}={ref.path}" for ref in runs))
    lines.append("")

    if comparison.has_mock:
        lines += ["> **含 mock run：整表不可引用为实验结果。**", ""]

    lines += ["## Runs", "", "| run | tasks | benchmark | judge | git |", "|---|---|---|---|---|"]
    for ref in runs:
        bench = ref.summary.benchmark.benchmark if ref.summary.benchmark else "-"
        prov = ref.provenance
        judge = f"{prov.judging_model or 'n/a'}×{prov.judging_num_runs}" if prov else "-"
        git = (prov.git.commit or "n/a") if prov else "-"
        mark = "（baseline）" if ref.label == baseline else ""
        lines.append(f"| {ref.label}{mark} | {ref.summary.n_tasks} | {bench} | {judge} | `{git}` |")
    lines.append("")

    header = ["metric", *comparison.labels]
    if baseline:
        header.append("Δ vs baseline")
    else:
        header.append("best")
    lines += ["## Metrics", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]

    for delta in comparison.deltas:
        cells = [f"`{delta.metric}`"]
        for label in comparison.labels:
            value = delta.values.get(label)
            cells.append("-" if value is None else f"{value:.4f}")
        if baseline:
            cells.append(_delta_cell(delta, comparison.labels, baseline))
        else:
            cells.append(delta.best_label() or "-")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    if comparison.warnings:
        lines += ["## Warnings（可比性）", ""]
        lines += [f"- {item}" for item in comparison.warnings]
        lines.append("")
    return "\n".join(lines)


def _delta_cell(delta: MetricDelta, labels: list[str], baseline: str) -> str:
    """非 baseline arm 的 Δ（多 arm 时逗号分隔），带方向箭头。"""
    parts: list[str] = []
    for label in labels:
        if label == baseline:
            continue
        diff = delta.delta(label)
        if diff is None:
            parts.append(f"{label}: -")
            continue
        arrow = _ARROW.get(bool(delta.improved(label)), "")
        parts.append(f"{label}: {diff:+.4f} {arrow}".strip())
    return ", ".join(parts) or "-"


def write_comparison(comparison: RunComparison, runs: list[RunRef], output_dir: str | Path) -> Path:
    """落盘 comparison.md + comparison.json，返回目录。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison.md").write_text(render_markdown(comparison, runs), encoding="utf-8")
    (out / "comparison.json").write_text(
        json.dumps(comparison.model_dump(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return out
