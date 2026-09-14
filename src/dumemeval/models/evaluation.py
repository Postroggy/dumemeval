from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentOutput(BaseModel):
    """agent 对单个查询（回合/问题）的输出。"""

    query: str = Field(description="触发该输出的查询（round/question）")
    output: str = Field(description="agent 的输出内容")


class BenchmarkMetrics(BaseModel):
    """数据集自己的指标结果（替代返回裸 dict）。"""

    name: str = Field(description="数据集名")
    values: dict[str, float] = Field(default_factory=dict, description="指标名 → 值")
    by_category: dict[str, dict[str, float]] = Field(
        default_factory=dict, description="类别分指标（如 LoCoMo multi_hop/temporal）"
    )
    details: list[dict[str, Any]] = Field(default_factory=list)

    def get(self, metric: str, default: float = 0.0) -> float:
        """按指标名取值。"""
        return self.values.get(metric, default)

    def __getitem__(self, metric: str) -> float:
        return self.values[metric]
