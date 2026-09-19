"""Public registry and package imports remain usable after moving the integration."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "first",
    [
        "dumemeval.benchmarks.memoryarena.datasets.shopping",
        "dumemeval.benchmarks.memoryarena.metrics.travel",
        "dumemeval.benchmarks.memoryarena.environment.providers",
        "dumemeval.benchmarks.memoryarena.environment.runtime",
        "dumemeval.datasets.benchmark",
        "dumemeval.metrics.core.registry",
        "dumemeval.environments",
    ],
)
def test_direct_import_and_registries_without_optional_worker_sdks(first: str, tmp_path: Path) -> None:
    script = """
import importlib
import importlib.abc
import sys
class NoOptionalWorker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastapi', 'uvicorn', 'harbor', 'openai', 'anthropic'}:
            raise ImportError('Optional worker dependency imported eagerly: ' + fullname)
sys.meta_path.insert(0, NoOptionalWorker())
importlib.import_module(sys.argv[1])
from dumemeval.datasets import benchmark_names, get_benchmark
from dumemeval.metrics import calculator_names, get_benchmark_calculator, MemoryArenaTravelCalculator
from dumemeval.environments import get_task_environment, WebshopTaskEnvironment
for scene in ('math', 'phys', 'search', 'shopping', 'travel'):
    name = 'memoryarena_' + scene
    assert name in benchmark_names() and name in calculator_names()
    assert get_benchmark(name).name == name
    assert get_benchmark_calculator(name).name == name
assert isinstance(get_benchmark_calculator('memoryarena'), MemoryArenaTravelCalculator)
assert isinstance(get_task_environment('webshop'), WebshopTaskEnvironment)
assert get_task_environment('memoryarena').name == 'memoryarena'
"""
    subprocess.run(
        [sys.executable, "-c", script, first],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_registered_overrides_survive_registry_lookups(tmp_path: Path) -> None:
    script = """
from dumemeval.datasets.benchmark import BenchmarkAdapter, get_benchmark, register_benchmark
from dumemeval.metrics import MetricCalculator, get_benchmark_calculator, register_calculator
from dumemeval.environments import HttpTaskEnvironment, get_task_environment, register_task_environment
class CustomData(BenchmarkAdapter):
    name = 'memoryarena_math'
    @property
    def data_type(self):
        return None
    def build_tasks(self, data):
        return []
class CustomMetric(MetricCalculator):
    name = 'memoryarena_math'
    kind = 'benchmark'
    def calculate(self, inp):
        return None
class CustomEnvironment(HttpTaskEnvironment):
    name = 'memoryarena'
register_benchmark(CustomData)
register_calculator(CustomMetric, 'memoryarena')
register_task_environment(CustomEnvironment)
assert isinstance(get_benchmark('memoryarena_math'), CustomData)
assert isinstance(get_benchmark_calculator('memoryarena_math'), CustomMetric)
assert isinstance(get_benchmark_calculator('memoryarena'), CustomMetric)
assert isinstance(get_task_environment('memoryarena'), CustomEnvironment)
"""
    subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, check=True, capture_output=True, text=True, timeout=60
    )
