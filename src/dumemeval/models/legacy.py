from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .evaluation import BenchmarkMetrics
from .execution import MemoryOp
from .metrics import EfficiencyResult, QualityResult, TraceResult, UtilityResult


class EvalResult(BaseModel):
    """一次评测的完整结果。"""

    task_name: str
    memory_backend: str
    quality: QualityResult = Field(default_factory=QualityResult)
    utility: UtilityResult = Field(default_factory=UtilityResult)
    efficiency: EfficiencyResult = Field(default_factory=EfficiencyResult)
    trace: TraceResult | None = Field(default=None, description="agent 行为体检（未测为 None）")
    benchmark: BenchmarkMetrics | None = Field(default=None, description="数据集指标（若有）")
    metrics: dict[str, float] = Field(
        default_factory=dict, description="聚合后的扁平指标（quality.recall / locomo.f1 …）"
    )
    session_outcomes: list[dict[str, Any]] = Field(
        default_factory=list, description="session 执行摘要（供 MetricsAggregator 使用）"
    )
    memory_ops: list[MemoryOp] = Field(default_factory=list)
    artifacts: dict[str, Path] = Field(default_factory=dict)
