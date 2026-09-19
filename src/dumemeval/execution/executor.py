"""执行器协议：SessionRunner 与具体执行器解耦。

设计要点：
- SessionExecutor 是抽象基类：run_session() 是唯一契约
- MockRunner（模拟）/ HarborBridge（Harbor 隔离环境）都实现它
- **不依赖 adapters**：memory 读写由 SessionRunner 自己调 adapter，
  执行器只负责"在环境里跑 agent"
- SessionOutcome 定义在 models（结果模型层），此处再导出供执行器使用
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from ..models import EvalTask, SessionOutcome, SessionSpec

__all__ = ["SessionExecutor", "SessionOutcome"]


class SessionExecutor(ABC):
    """会话执行器协议：在隔离/模拟环境里跑一个 session。

    注意：执行器不感知 memory 后端（不接收 adapter 参数）。
    memory 生命周期（注入/快照/收集）由 SessionRunner 编排。
    """

    @asynccontextmanager
    async def task_scope(self, task: EvalTask, output_dir: Path) -> AsyncIterator[SessionExecutor]:
        """Acquire optional task resources; stateless executors simply reuse themselves."""
        yield self

    @abstractmethod
    async def run_session(
        self,
        session: SessionSpec,
        session_ctx: dict[str, Any],
    ) -> SessionOutcome:
        """执行单个 session。

        Args:
            session: session 定义
            session_ctx: 跨 session 上下文（memory 注入的 env/mount 等），
                执行器可读写

        Returns:
            SessionOutcome: 执行结果
        """
        raise NotImplementedError
