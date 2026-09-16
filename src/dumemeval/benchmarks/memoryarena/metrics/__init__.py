"""MemoryArena official scoring policies and their registry aliases."""

from .reasoning import MemoryArenaMathCalculator, MemoryArenaPhysCalculator
from .search import MemoryArenaSearchCalculator
from .shopping import MemoryArenaShoppingCalculator
from .travel import MemoryArenaTravelCalculator, judge_round

CALCULATORS = (
    MemoryArenaMathCalculator,
    MemoryArenaPhysCalculator,
    MemoryArenaSearchCalculator,
    MemoryArenaShoppingCalculator,
    MemoryArenaTravelCalculator,
)

ALIASES = {"memoryarena": MemoryArenaTravelCalculator}

__all__ = [
    "ALIASES",
    "CALCULATORS",
    "MemoryArenaMathCalculator",
    "MemoryArenaPhysCalculator",
    "MemoryArenaSearchCalculator",
    "MemoryArenaShoppingCalculator",
    "MemoryArenaTravelCalculator",
    "judge_round",
]
