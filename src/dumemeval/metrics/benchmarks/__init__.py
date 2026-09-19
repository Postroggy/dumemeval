"""各数据集官方口径计算器。

与 dimensions/（横切四维）区分：这里每个文件绑定一个外部数据集，
实现该数据集官方的打分口径（来源见各文件 docstring 的 Source 标注）。
新增数据集：实现 MetricCalculator 子类 → 在 metrics/__init__.py 注册。
"""

from typing import TYPE_CHECKING

from dumemeval.benchmarks.memoryarena import metrics as _memoryarena  # noqa: F401

if TYPE_CHECKING:
    from dumemeval.benchmarks.memoryarena.metrics import (
        MemoryArenaMathCalculator,
        MemoryArenaPhysCalculator,
        MemoryArenaSearchCalculator,
        MemoryArenaShoppingCalculator,
        MemoryArenaTravelCalculator,
        judge_round,
    )

from .beam import BeamCalculator
from .clbench import CLBenchCalculator
from .evermembench_dynamic import EverMemBenchDynamicCalculator
from .halumem import HaluMemCalculator
from .locomo import (
    CATEGORY_MAPPING,
    JudgeFn,
    LoCoMoCalculator,
    locomo_f1,
    locomo_f1_multi,
    score_locomo_f1,
)
from .locomo_plus import LocomoPlusCalculator
from .longmemeval import LongMemEvalCalculator
from .memora import MemoraCalculator
from .memoryagentbench import MemoryAgentBenchCalculator
from .memorybench import MemoryBenchCalculator
from .memorycd import MemoryCDCalculator
from .memsim import MemSimCalculator
from .perltqa import PerLTQACalculator
from .personamem import PersonaMemCalculator
from .scriptmem import ScriptMemCalculator
from .streammembench import StreamMemBenchCalculator

__all__ = [
    "CATEGORY_MAPPING",
    "BeamCalculator",
    "CLBenchCalculator",
    "EverMemBenchDynamicCalculator",
    "HaluMemCalculator",
    "JudgeFn",
    "LoCoMoCalculator",
    "LocomoPlusCalculator",
    "LongMemEvalCalculator",
    "MemSimCalculator",
    "MemoraCalculator",
    "MemoryAgentBenchCalculator",
    "MemoryArenaMathCalculator",
    "MemoryArenaPhysCalculator",
    "MemoryArenaSearchCalculator",
    "MemoryArenaShoppingCalculator",
    "MemoryArenaTravelCalculator",
    "MemoryBenchCalculator",
    "MemoryCDCalculator",
    "PerLTQACalculator",
    "PersonaMemCalculator",
    "ScriptMemCalculator",
    "StreamMemBenchCalculator",
    "judge_round",
    "locomo_f1",
    "locomo_f1_multi",
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
