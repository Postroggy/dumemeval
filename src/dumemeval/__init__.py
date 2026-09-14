"""DuMemEval：评测带记忆的 Agent。

在隔离环境里跨 session 地记、取、用；同时报告 Memory 质量（Quality）、
任务效用（Utility）、系统效率（Efficiency）、Agent 行为（Trace）；
官方数据集给出可复现口径。

扩展点（社区改这些，不要改 SessionRunner 主循环）：
- adapters.registry.register_adapter
- core.protocol.register_protocol
- datasets.benchmark.register_benchmark
- metrics.core.registry.register_calculator
- environments.register_task_environment
"""

from importlib.metadata import version as _pkg_version

__version__ = _pkg_version("dumemeval")
