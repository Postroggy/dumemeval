"""BenchmarkAdapter：数据集适配协议。

设计要点：
- 只负责把类型化 benchmark 数据转换为可执行的 EvalTask
- 判分和官方指标聚合由 evaluation 层负责
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cache
from typing import Any, ClassVar

from pydantic import BaseModel

from ..models import AgentOutput, BenchmarkMetrics, EvalTask


class BenchmarkData(BaseModel, ABC):
    """数据集原始数据的类型化包装。

    子类定义自己的字段（如 LoCoMoData.conversations）。
    加载层（DatasetLoader）产出后，由适配器子类解析成具体类型。
    """

    @classmethod
    @abstractmethod
    def from_raw(cls, raw: Any) -> BenchmarkData:
        """从加载的原始数据构造（原始数据来自 DatasetLoader）。"""
        raise NotImplementedError


class BenchmarkAdapter(ABC):
    """数据集适配协议。

    子类实现：
        name:            数据集名（registry 用）
        data_type:       BenchmarkData 子类（该数据集的数据类型）
        build_tasks():   从类型化数据构建 EvalTask 列表（供执行管线运行）
    """

    name: ClassVar[str] = ""

    @property
    @abstractmethod
    def data_type(self) -> type[BenchmarkData]:
        """该数据集的数据类型（BenchmarkData 子类）。"""
        raise NotImplementedError

    @abstractmethod
    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        """从类型化数据构建 EvalTask 列表。

        适配器自定义参数（如 ``subset`` / ``max_questions``）由**具体子类**
        声明为具名关键字参数，经配置 ``task.benchmark_options`` 透传——
        基类不设 ``**options``（避免调用方绕过子类签名约束）。
        """
        raise NotImplementedError

    def metrics(self) -> list[str]:
        """Official metric names declared by the matching calculator."""
        from ..evaluation import declared_metric_names

        return declared_metric_names(self.name)

    def evaluate(
        self,
        task: EvalTask,
        outputs: list[AgentOutput],
    ) -> BenchmarkMetrics:
        """Direct scoring API backed by evaluation.BenchmarkScorer."""
        from ..evaluation import CalculatorBenchmarkScorer
        from ..metrics.core.base import MetricInput

        options: dict[str, Any] = {}
        judge = getattr(self, "_judge", None)
        if judge is not None:
            options["judge"] = judge
        judgement_mode = getattr(self, "judgement_mode", None)
        if judgement_mode is not None:
            options["judgement_mode"] = judgement_mode
        lang = getattr(self, "lang", None)
        if lang is not None:
            options["lang"] = lang
        scored = CalculatorBenchmarkScorer(self.name, **options).score(
            MetricInput(task=task, outputs=outputs)
        )
        return BenchmarkMetrics(
            name=scored.benchmark,
            values=scored.values,
            by_category=scored.by_category,
            details=scored.details,
        )


# ── 注册表 ──────────────────────────────────────────────────────────────────

_BENCHMARK_REGISTRY: dict[str, type[BenchmarkAdapter]] = {}


@cache
def _load_builtin_integrations() -> None:
    from ..benchmarks.memoryarena.datasets import ADAPTERS

    for cls in ADAPTERS:
        _BENCHMARK_REGISTRY.setdefault(cls.name, cls)


def register_benchmark(cls: type[BenchmarkAdapter]) -> type[BenchmarkAdapter]:
    """注册 benchmark 适配器（装饰器）。"""
    _BENCHMARK_REGISTRY[cls.name] = cls
    return cls


def get_benchmark(name: str) -> BenchmarkAdapter:
    """按名创建 benchmark 适配器实例。"""
    _load_builtin_integrations()
    cls = _BENCHMARK_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown benchmark: {name!r}. Supported: {list(_BENCHMARK_REGISTRY)}")
    return cls()


def benchmark_names() -> list[str]:
    """所有已注册的 benchmark 名。"""
    _load_builtin_integrations()
    return list(_BENCHMARK_REGISTRY)
