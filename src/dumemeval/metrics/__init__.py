"""统一指标计算层。

一次评测 → MetricsAggregator → MetricReport（扁平 + 类型化 quality/utility/efficiency/trace）。
Benchmark 计算器走注册表：加数据集不必改 get_benchmark_calculator 的分支。

分层：
- core/：基础设施（计算器协议 / 聚合器 / 注册表 / LLM judge / memory 探测）
- dimensions/：横切四维（quality / utility / efficiency / trace）
- benchmarks/：各数据集官方口径计算器
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dumemeval.benchmarks.memoryarena.metrics import (
        MemoryArenaMathCalculator,
        MemoryArenaPhysCalculator,
        MemoryArenaSearchCalculator,
        MemoryArenaShoppingCalculator,
        MemoryArenaTravelCalculator,
        judge_round,
    )

from .benchmarks import (
    CATEGORY_MAPPING,
    BeamCalculator,
    CLBenchCalculator,
    EverMemBenchDynamicCalculator,
    HaluMemCalculator,
    JudgeFn,
    LoCoMoCalculator,
    LocomoPlusCalculator,
    LongMemEvalCalculator,
    MemoraCalculator,
    MemoryAgentBenchCalculator,
    MemoryBenchCalculator,
    MemoryCDCalculator,
    MemSimCalculator,
    PerLTQACalculator,
    PersonaMemCalculator,
    ScriptMemCalculator,
    StreamMemBenchCalculator,
    locomo_f1,
    locomo_f1_multi,
    score_locomo_f1,
)
from .core import (
    AggregatedMetrics,
    MetricBundle,
    MetricCalculator,
    MetricInput,
    MetricsAggregator,
    calculator_names,
    declared_metric_names,
    get_benchmark_calculator,
    outputs_from_execution,
    prediction_for_item,
    register_calculator,
    round_items,
)
from .dimensions import (
    EfficiencyCalculator,
    EfficiencyEvaluator,
    QualityCalculator,
    QualityEvaluator,
    TraceCalculator,
    UtilityCalculator,
    UtilityEvaluator,
)

for _cls in (
    BeamCalculator,
    CLBenchCalculator,
    EverMemBenchDynamicCalculator,
    HaluMemCalculator,
    LoCoMoCalculator,
    LocomoPlusCalculator,
    LongMemEvalCalculator,
    MemoryAgentBenchCalculator,
    MemoryBenchCalculator,
    PerLTQACalculator,
    PersonaMemCalculator,
    ScriptMemCalculator,
    StreamMemBenchCalculator,
    MemSimCalculator,
    MemoraCalculator,
    MemoryCDCalculator,
):
    register_calculator(_cls)

__all__ = [
    "CATEGORY_MAPPING",
    "AggregatedMetrics",
    "BeamCalculator",
    "CLBenchCalculator",
    "EfficiencyCalculator",
    "EfficiencyEvaluator",
    "EverMemBenchDynamicCalculator",
    "HaluMemCalculator",
    "JudgeFn",
    "LoCoMoCalculator",
    "LocomoPlusCalculator",
    "LongMemEvalCalculator",
    "MemoryAgentBenchCalculator",
    "MemoryArenaMathCalculator",
    "MemoryArenaPhysCalculator",
    "MemoryArenaSearchCalculator",
    "MemoryArenaShoppingCalculator",
    "MemoryArenaTravelCalculator",
    "MemoryBenchCalculator",
    "MetricBundle",
    "MetricCalculator",
    "MetricInput",
    "MetricsAggregator",
    "PerLTQACalculator",
    "PersonaMemCalculator",
    "QualityCalculator",
    "QualityEvaluator",
    "ScriptMemCalculator",
    "StreamMemBenchCalculator",
    "TraceCalculator",
    "UtilityCalculator",
    "UtilityEvaluator",
    "calculator_names",
    "declared_metric_names",
    "get_benchmark_calculator",
    "judge_round",
    "locomo_f1",
    "locomo_f1_multi",
    "outputs_from_execution",
    "prediction_for_item",
    "register_calculator",
    "round_items",
    "score_locomo_f1",
]


def __getattr__(name: str) -> object:
    """Keep published calculator exports while avoiding eager integration imports."""
    if name in {
        "MemoryArenaSearchCalculator",
        "MemoryArenaShoppingCalculator",
        "MemoryArenaTravelCalculator",
        "MemoryArenaMathCalculator",
        "MemoryArenaPhysCalculator",
        "judge_round",
    }:
        from dumemeval.benchmarks.memoryarena import metrics

        return getattr(metrics, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
