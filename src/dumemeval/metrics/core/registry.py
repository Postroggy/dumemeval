"""Benchmark 指标计算器注册表。

社区加数据集：实现 MetricCalculator 子类（设 ``name`` + ``kind="benchmark"``）后
调用 ``register_calculator(Cls)``——不必改 ``get_benchmark_calculator`` 的分支。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from typing import Any, Literal, cast

from .base import MetricCalculator

JudgeFn = Callable[[str, str, str], bool]

_REGISTRY: dict[str, type[MetricCalculator]] = {}
_ALIASES: dict[str, str] = {
    "memdaily": "memsim",
}


def register_calculator(cls: type[MetricCalculator], *aliases: str) -> type[MetricCalculator]:
    """注册计算器（及可选别名）。可作装饰器，也可在包初始化时调用。"""
    if not getattr(cls, "name", None):
        raise ValueError(f"{cls.__name__} must set ClassVar name")
    _REGISTRY[cls.name] = cls
    for alias in aliases:
        _REGISTRY[alias] = cls
    return cls


def calculator_names() -> list[str]:
    """已注册的规范名（按 ClassVar name 去重）。"""
    return sorted({cls.name for cls in _REGISTRY.values()})


def declared_metric_names(name: str) -> list[str]:
    """Official metric names declared by a registered calculator."""
    key = _ALIASES.get(name.strip().lower(), name.strip().lower())
    cls = _REGISTRY.get(key)
    if cls is None:
        return []
    declared = getattr(cls, "metrics", ())
    if isinstance(declared, Sequence) and not isinstance(declared, (str, bytes)):
        return [item for item in declared if isinstance(item, str)]
    return []


def get_benchmark_calculator(
    name: str,
    *,
    judge: JudgeFn | None = None,
    judgement_mode: str = "hint",
    lang: str = "zh",
    llm_config: dict[str, Any] | None = None,
) -> MetricCalculator:
    """按数据集名创建计算器。只把 ``__init__`` 声明过的参数传进去。"""
    key = _ALIASES.get(name.strip().lower(), name.strip().lower())
    cls = _REGISTRY.get(key)
    if cls is None:
        raise ValueError(f"Unknown benchmark calculator: {name!r}. Supported: {calculator_names()}")
    params = inspect.signature(cls.__init__).parameters
    kwargs: dict[str, Any] = {}
    if "judge" in params:
        kwargs["judge"] = judge
    if "judgement_mode" in params:
        mode = judgement_mode if judgement_mode in {"hint", "answer", "none"} else "hint"
        kwargs["judgement_mode"] = cast(Literal["hint", "answer", "none"], mode)
    if "lang" in params:
        kwargs["lang"] = lang
    if "llm_config" in params and llm_config is not None:
        kwargs["llm_config"] = llm_config
    return cls(**kwargs)
