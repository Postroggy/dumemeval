"""Registry inspection CLI."""

from __future__ import annotations

from typing import Literal

Kind = Literal["adapters", "benchmarks", "protocols", "all"]


def cmd_list(kind: Kind = "all") -> int:
    from ..adapters.registry import adapter_names
    from ..core.protocol import protocol_names
    from ..datasets import benchmark_names

    if kind in ("adapters", "all"):
        print("adapters: " + ", ".join(adapter_names()))
    if kind in ("protocols", "all"):
        print("protocols: " + ", ".join(protocol_names()))
    if kind in ("benchmarks", "all"):
        print("benchmarks: " + ", ".join(benchmark_names()))
    return 0
