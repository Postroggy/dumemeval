"""报告生成。

输出：markdown 报告 + JSON 结果。一次评测一份完整指标（result.metrics 聚合）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from ..core.config import ExperimentConfig
from ..models import TaskResult
from .provenance import RunProvenance, provenance_markdown

ReportFormat = Literal["json", "md", "json+md"]


class ReportGenerator:
    """生成评测报告。"""

    def __init__(self, output_dir: str | Path = "results"):
        self.output_dir = Path(output_dir)

    def generate(
        self,
        result: TaskResult,
        config: ExperimentConfig | None = None,
        provenance: RunProvenance | None = None,
        formats: ReportFormat = "json+md",
    ) -> Path:
        """Generate a report from TaskResult."""
        return self._write(
            run_dir=self.output_dir / f"{result.task_name}__{result.execution.memory_backend}",
            payload=result.model_dump(mode="json"),
            markdown=self._task_markdown(result, config, provenance),
            formats=formats,
        )

    def _write(
        self,
        *,
        run_dir: Path,
        payload: dict[str, Any],
        markdown: list[str],
        formats: ReportFormat,
    ) -> Path:
        run_dir.mkdir(parents=True, exist_ok=True)
        if formats in ("json", "json+md"):
            (run_dir / "result.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
            )
        if formats in ("md", "json+md"):
            (run_dir / "report.md").write_text("\n".join(markdown), encoding="utf-8")
        return run_dir

    @staticmethod
    def _meta_line(config: ExperimentConfig | None) -> str:
        if config is None:
            return ""
        return " | ".join(
            part for part in (config.experiment.protocol, config.agent.runtime, config.memory.type) if part
        )

    def _task_markdown(
        self,
        result: TaskResult,
        config: ExperimentConfig | None,
        provenance: RunProvenance | None,
    ) -> list[str]:
        lines = [
            f"# {result.task_name} — {result.execution.memory_backend}",
            "",
            self._meta_line(config),
            f"status: {result.execution.status}",
        ]
        if provenance is not None:
            lines += ["", *provenance_markdown(provenance, heading=False)]
        metrics = result.metrics
        if metrics and metrics.quality is not None:
            q = metrics.quality
            skipped = sum(str(d.get("label") or "") == "SKIPPED" for d in q.details)
            lines += ["", "## Quality", f"- precision: {q.precision:.3f}", f"- recall: {q.recall:.3f}"]
            if q.details:
                lines += [f"- judge: {len(q.details) - skipped}/{len(q.details)} 完成"]
                if skipped:
                    lines += [f"- SKIPPED: {skipped}"]
        if metrics and metrics.utility is not None:
            u = metrics.utility
            lines += [
                "",
                "## Utility",
                f"- task_success: {u.task_success}",
                f"- success_rate: {u.success_rate:.3f}",
            ]
        if result.benchmark:
            lines += ["", f"## Benchmark ({result.benchmark.benchmark})"]
            lines += [f"- {k}: {v:.4f}" for k, v in result.benchmark.values.items()]
        if result.metrics:
            lines += ["", "## Metrics"] + [f"- {k}: {v:.4f}" for k, v in result.metrics.flat.items()]
        return lines
