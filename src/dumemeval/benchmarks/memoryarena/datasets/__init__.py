"""MemoryArena adapters register through the existing dataset extension point."""

from .reasoning import MemoryArenaMathAdapter, MemoryArenaPhysAdapter
from .search import MemoryArenaSearchAdapter
from .shopping import MemoryArenaShoppingAdapter
from .travel import MemoryArenaTravelAdapter

__all__ = [
    "MemoryArenaMathAdapter",
    "MemoryArenaPhysAdapter",
    "MemoryArenaSearchAdapter",
    "MemoryArenaShoppingAdapter",
    "MemoryArenaTravelAdapter",
]
