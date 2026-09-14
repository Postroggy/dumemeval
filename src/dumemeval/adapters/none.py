"""无 Memory 后端：所有生命周期 no-op（框架不接入外部 memory 的 baseline 表达）。

``memory.type: none`` 的语义边界（见 docs/architecture/run-artifacts.md）：

- **只表达一件事**：本框架不接入任何外部的第三方 memory 系统——不注入、不观测、
  不快照。
- **不代表**「被测 agent 没有 memory 能力」：agent runtime（hermes / Claude Code 等）
  自身是否带原生 memory 是 runtime 的属性。``none`` 下 agent 仍可能自行读写其原生
  memory，但框架没有观测通道——「agent 到底用没用 runtime 自带 memory」留给用户
  自己判断（要观测它需对 runtime memory 目录做挂载/分析，或换 hermes_builtin 等
  显式接入其内置 memory 的 adapter）。

baseline 语义（谁当基线）由用户 ``dumemeval compare --baseline`` 决定，
本适配器只提供表达选项，不强制。

注意：``inject`` 刻意不写任何注入通道（memory_mounts / agent_env）——
这就是「无外部 memory」的本意。契约测试 ``test_inject_declares_a_channel``
对 ``none`` 例外放行（见 tests/test_adapter_contract.py 的 ``_NOOP``）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import EvalTask, MemorySpec, SessionSpec
from .base import BaseMemoryAdapter
from .registry import register_adapter


@register_adapter
class NoneMemoryAdapter(BaseMemoryAdapter):
    """无 memory 后端：setup / seed / inject / snapshot / observe 全部 no-op。"""

    type_name = "none"

    def __init__(self, spec: MemorySpec) -> None:
        super().__init__(spec)

    def setup(self, task: EvalTask) -> None:
        self._ops.clear()

    def inject(self, session: SessionSpec, session_ctx: dict[str, Any]) -> None:
        # 刻意不写通道：没有 memory 可注入
        return None

    def snapshot(self, session: SessionSpec, snapshot_dir: Path) -> Path:
        snap = snapshot_dir / f"session_{session.id}"
        snap.mkdir(parents=True, exist_ok=True)
        return snap

    def observe(self, session: SessionSpec) -> list[Any]:
        return []

    def memory_usage_hint(self) -> str | None:
        return None
