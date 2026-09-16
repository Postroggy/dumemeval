"""MemoryArena official scoring policies and their registry aliases."""

from dumemeval.metrics.core.registry import register_calculator

from .reasoning import MemoryArenaMathCalculator, MemoryArenaPhysCalculator
from .search import MemoryArenaSearchCalculator
from .shopping import MemoryArenaShoppingCalculator
from .travel import MemoryArenaTravelCalculator, judge_round

for _cls in (
    MemoryArenaMathCalculator,
    MemoryArenaPhysCalculator,
    MemoryArenaSearchCalculator,
    MemoryArenaShoppingCalculator,
):
    register_calculator(_cls)

register_calculator(MemoryArenaTravelCalculator, "memoryarena")

__all__ = [
    "MemoryArenaMathCalculator",
    "MemoryArenaPhysCalculator",
    "MemoryArenaSearchCalculator",
    "MemoryArenaShoppingCalculator",
    "MemoryArenaTravelCalculator",
    "judge_round",
]
