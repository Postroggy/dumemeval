"""Bind registered task environments around any real session executor."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from ..core.instructions import instruction_digest
from ..environments import get_task_environment
from ..models import EvalTask, SessionOutcome, SessionSpec, TaskEnvSpec
from ..task_environments.base import TaskEnvironmentRuntime
from .executor import SessionExecutor


async def _settle[T](operation: Awaitable[T]) -> T:
    """Join owned blocking work before cancellation can trigger resource cleanup."""
    worker = asyncio.ensure_future(operation)
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        with suppress(Exception):
            await worker
        raise


class EnvironmentExecutor(SessionExecutor):
    """Keep environment ownership outside the agent and the memory lifecycle."""

    def __init__(self, executor: SessionExecutor, runtime: TaskEnvironmentRuntime | None = None) -> None:
        self.executor = executor
        self.runtime = runtime

    @asynccontextmanager
    async def task_scope(self, task: EvalTask, output_dir: Path) -> AsyncIterator[SessionExecutor]:
        runtime = None
        if task.task_environment:
            spec = TaskEnvSpec.model_validate(task.task_environment)
            runtime = get_task_environment(spec.type).create_runtime(task, spec, output_dir)
        async with self.executor.task_scope(task, output_dir) as executor:
            if runtime is None:
                yield executor
                return
            error: BaseException | None = None
            try:
                await _settle(asyncio.to_thread(runtime.open))
                yield EnvironmentExecutor(executor, runtime)
            except BaseException as exc:
                error = exc
                raise
            finally:
                try:
                    await _settle(asyncio.to_thread(runtime.close))
                except Exception as cleanup_error:
                    if error is None:
                        raise
                    error.add_note(f"Environment cleanup also failed: {type(cleanup_error).__name__}")

    async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
        if self.runtime is None:
            return await self.executor.run_session(session, session_ctx)
        binding = await _settle(asyncio.to_thread(self.runtime.begin_session, session))
        context = dict(session_ctx)
        context["agent_env"] = {**session_ctx.get("agent_env", {}), **binding.env}
        context["runtime_mounts"] = binding.mounts
        context["instruction_suffix"] = "\n\n".join(
            part for part in (session_ctx.get("instruction_suffix", ""), binding.instruction) if part
        )
        outcome = SessionOutcome(session_id=session.id)
        cancelled = False
        try:
            outcome = await self.executor.run_session(session, context)
        except asyncio.CancelledError:
            cancelled = True
            outcome.error = "Session execution was cancelled"
            raise
        except Exception as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
        finally:
            if "trial_dir" in context:
                session_ctx["trial_dir"] = context["trial_dir"]
            try:
                outcome = await _settle(asyncio.to_thread(self.runtime.finish_session, session, outcome))
            except Exception as exc:
                if not cancelled:
                    outcome.success = False
                    outcome.error = (
                        outcome.error or ""
                    ) + f"; environment finalization failed: {type(exc).__name__}"
        if outcome.instruction_sha256 is None:
            outcome.instruction_sha256 = instruction_digest(
                session.instruction, str(context.get("instruction_suffix") or "")
            )
        return outcome
