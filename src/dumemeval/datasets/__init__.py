"""数据管理：加载 + benchmark 适配。"""

from . import benchmarks as _benchmarks  # noqa: F401  触发内置 benchmark 注册
from .benchmark import BenchmarkAdapter, benchmark_names, get_benchmark
from .prepare import DatasetSpec, dataset_names, downloadable_names, prepare_dataset

__all__ = [
    "BenchmarkAdapter",
    "DatasetSpec",
    "benchmark_names",
    "dataset_names",
    "downloadable_names",
    "get_benchmark",
    "prepare_dataset",
]
