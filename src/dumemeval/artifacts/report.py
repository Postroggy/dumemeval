"""报告生成。

输出：markdown 报告 + JSON 结果。一次评测一份完整指标（result.metrics 聚合）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import TaskResult
from .provenance import RunProvenance


class ReportGenerator:
    """生成评测报告。"""

    def __init__(self, output_dir: str | Path = "results"):
        self.output_dir = Path(output_dir)

    def generate_task(
        self,
        result: TaskResult,
        config: dict[str, Any] | None = None,
        provenance: RunProvenance | None = None,
        formats: str = "json+md",
    ) -> Path:
        """Generate a report from the typed evaluation result."""
        run_dir = self.output_dir / f"{result.task_name}__{result.execution.memory_backend}"
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = result.model_dump(mode="json")
        if formats in ("json", "json+md"):
            (run_dir / "result.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        if formats in ("md", "json+md"):
            lines = [
                f"# {result.task_name} — {result.execution.memory_backend}",
                "",
                f"status: {result.execution.status}",
            ]
            if result.benchmark:
                lines += ["", f"## Benchmark ({result.benchmark.benchmark})"]
                lines += [f"- {k}: {v:.4f}" for k, v in result.benchmark.values.items()]
            if result.metrics:
                lines += ["", "## Metrics"] + [f"- {k}: {v:.4f}" for k, v in result.metrics.flat.items()]
            (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
        return run_dir
