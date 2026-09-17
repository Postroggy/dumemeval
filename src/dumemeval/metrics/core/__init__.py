"""指标基础设施：计算器协议 / 聚合器 / 注册表 / memory 探测。

LLM judge 不在这里——判分体系统一在 ``verifier/``（``LLMJudgeVerifier`` +
``make_llm_judge`` 工厂），metrics 只消费判分结果。
"""

from .base import (
    AggregatedMetrics,
    MetricBundle,
    MetricCalculator,
    MetricInput,
    MetricsAggregator,
    outputs_from_execution,
    prediction_for_item,
    round_items,
)
from .probe import QualityProbe
from .registry import calculator_names, declared_metric_names, get_benchmark_calculator, register_calculator

__all__ = [
    "AggregatedMetrics",
    "MetricBundle",
    "MetricCalculator",
    "MetricInput",
    "MetricsAggregator",
    "QualityProbe",
    "calculator_names",
    "declared_metric_names",
    "get_benchmark_calculator",
    "outputs_from_execution",
    "prediction_for_item",
    "register_calculator",
    "round_items",
]
