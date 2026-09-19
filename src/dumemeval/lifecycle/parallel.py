"""跨 task 并行编排（n_concurrent 限流）。

并行层次（关键设计）：
- task 间并行：不同对话样本彼此独立 → asyncio.TaskGroup + Semaphore(n_concurrent)
- task 内 session 恒串行：session N 写的 memory 要喂给 session N+1 的 inject
  （跨 session 记忆演化正是被测能力），并行会破坏评测语义

隔离（并行正确性）：
- adapter per-task 实例：memory 目录按 task 分（adapter_factory 负责），
  run 后经 self.adapters[task.name] 取回（read_memory_files 等聚合用）
- MemoryTransfer / snapshot 目录按 task 分子目录
- trial_name / task_dir 由 HarborBridge 按 session_ctx["task_name"] 隔离
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from ..adapters.base import BaseMemoryAdapter
from ..core.protocol import EvalProtocol
from ..execution.executor import SessionExecutor, SessionOutcome
from ..models import EvalTask, TaskExecution
from .checkpoint import load_task_result, save_task_result
from .memory_transfer import MemoryTransfer
from .runner import SessionRunner

logger = logging.getLogger(__name__)


class ParallelTaskRunner:
    """task 级并行编排器（task 内 session 串行）。

    Usage:
        runner = ParallelTaskRunner(
            adapter_factory=lambda name: create_adapter(spec_for(name)),
            executor=executor,  # 无状态可共享（task_name 经 session_ctx 隔离）
            output_dir="results",
            n_concurrent=4,
        )
        results = await runner.run(tasks)  # 保序（与 tasks 对齐）
        runner.adapters[task.name].read_memory_files()  # per-task memory
    """

    def __init__(
        self,
        adapter_factory: Callable[[str], BaseMemoryAdapter],
        executor: SessionExecutor,
        protocol: EvalProtocol | None = None,
        output_dir: str | Path = "results",
        n_concurrent: int = 1,
        resume: bool = False,
    ):
        if n_concurrent < 1:
            raise ValueError(f"n_concurrent must be >= 1, got {n_concurrent}")
        self.adapter_factory = adapter_factory
        self.executor = executor
        self.protocol = protocol
        self.output_dir = Path(output_dir)
        self.n_concurrent = n_concurrent
        self.resume = resume
        self.adapters: dict[str, BaseMemoryAdapter] = {}

    async def run(self, tasks: list[EvalTask]) -> list[TaskExecution]:
        """并行执行所有 task，返回结果列表（与 tasks 顺序对齐）。

        单个 task 失败不中断其余 task：转成带 error 的 TaskExecution
        （错误显式进入结果与日志，最终报告可见，不静默吞掉）。
        """
        semaphore = asyncio.Semaphore(self.n_concurrent)
        results: dict[str, TaskExecution] = {}

        async def _run_one(task: EvalTask) -> None:
            async with semaphore:
                try:
                    results[task.name] = await self._run_task(task)
                except Exception as e:
                    # 兼容性回退（单 task 失败不影响整批评测），非吞异常：
                    # 错误写入 TaskExecution.sessions 并记日志
                    logger.exception("task %s 编排失败", task.name)
                    failed = TaskExecution(
                        task_id=task.name,
                        task_name=task.name,
                        memory_backend="(failed)",
                        status="failed",
                        error=f"{type(e).__name__}: {e}",
                    )
                    # session_id 从 1 起（SessionOutcome 约束 >= 1）；0 为非法
                    failed.sessions.append(
                        SessionOutcome(session_id=1, success=False, error=f"{type(e).__name__}: {e}")
                    )
                    results[task.name] = failed

        async with asyncio.TaskGroup() as tg:
            for task in tasks:
                tg.create_task(_run_one(task))

        return [results[task.name] for task in tasks]

    async def _run_task(self, task: EvalTask) -> TaskExecution:
        """单 task 串行执行（per-task adapter / transfer / snapshot 目录隔离）。"""
        adapter = self.adapter_factory(task.name)
        self.adapters[task.name] = adapter
        if self.resume:
            cached = load_task_result(self.output_dir, task.name)
            if cached is not None:
                logger.info("resume: 跳过已完成 task %s", task.name)
                return cached
        result: TaskExecution | None = None
        attempt = uuid4().hex
        try:
            async with self.executor.task_scope(task, self.output_dir) as executor:
                runner = SessionRunner(
                    adapter=adapter,
                    executor=executor,
                    protocol=self.protocol,
                    snapshot_dir=self.output_dir / "snapshots" / adapter.name / task.name,
                    memory_transfer=MemoryTransfer(
                        transfer_dir=self.output_dir / "memory" / "transfer" / task.name / attempt,
                        mount_source=self.output_dir / "memory" / "mounts" / task.name / attempt,
                    ),
                )
                result = await runner.run(task)
        except Exception as exc:
            if result is None:
                raise
            result.status = "failed"
            result.error = f"Task resource cleanup failed: {type(exc).__name__}: {exc}"
        save_task_result(self.output_dir, result)
        return result
