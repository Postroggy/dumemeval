"""Five scene adapters, loaded by the shared dataset registry."""

from .reasoning import MemoryArenaMathAdapter, MemoryArenaPhysAdapter
from .search import MemoryArenaSearchAdapter
from .shopping import MemoryArenaShoppingAdapter
from .travel import MemoryArenaTravelAdapter

ADAPTERS = (
    MemoryArenaMathAdapter,
    MemoryArenaPhysAdapter,
    MemoryArenaSearchAdapter,
    MemoryArenaShoppingAdapter,
    MemoryArenaTravelAdapter,
)
