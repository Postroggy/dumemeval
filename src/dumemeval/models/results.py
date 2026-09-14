"""Immutable-by-convention boundaries between execution and evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .execution import MemoryOp, SessionOutcome
from .metrics import EfficiencyResult, QualityResult, TraceResult, UtilityResult


class TaskExecution(BaseModel):
    task_id: str
    task_name: str
    memory_backend: str
    sessions: list[SessionOutcome] = Field(default_factory=list)
    memory_ops: list[MemoryOp] = Field(default_factory=list)
    artifacts: dict[str, Path] = Field(default_factory=dict)
    status: Literal["completed", "failed", "partial"] = "completed"
    error: str | None = None


class Verdict(BaseModel):
    label: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class SampleResult(BaseModel):
    sample_id: str
    query: str
    response: str
    ground_truth: str | None = None
    session_id: int | None = None
    category: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    verdict: Verdict | None = None


class BenchmarkResult(BaseModel):
    benchmark: str
    primary_metric: str | None = None
    values: dict[str, float] = Field(default_factory=dict)
    by_category: dict[str, dict[str, float]] = Field(default_factory=dict)
    details: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def primary_score(self) -> float | None:
        return self.values.get(self.primary_metric) if self.primary_metric else None


class MetricReport(BaseModel):
    quality: QualityResult | None = None
    utility: UtilityResult | None = None
    efficiency: EfficiencyResult | None = None
    trace: TraceResult | None = None
    flat: dict[str, float] = Field(default_factory=dict)


class TaskResult(BaseModel):
    task_id: str
    task_name: str
    execution: TaskExecution
    samples: list[SampleResult] = Field(default_factory=list)
    benchmark: BenchmarkResult | None = None
    metrics: MetricReport | None = None
