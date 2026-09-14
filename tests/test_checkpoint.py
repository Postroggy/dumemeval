"""测试：跨 task 断点续跑（已完成 task 跳过，未完成的重跑）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dumemeval.adapters.base import BaseMemoryAdapter
from dumemeval.execution.executor import SessionExecutor, SessionOutcome
from dumemeval.lifecycle.checkpoint import load_task_result, save_task_result, task_checkpoint_path
from dumemeval.lifecycle.parallel import ParallelTaskRunner
from dumemeval.models import EvalTask, MemorySpec, SessionSpec, TaskExecution


class _StubAdapter(BaseMemoryAdapter):
    def setup(self, task: EvalTask) -> None:
        return None

    def inject(self, session: SessionSpec, session_ctx: dict[str, Any]) -> None:
        return None

    def snapshot(self, session: SessionSpec, snapshot_dir: Path) -> Path:
        return snapshot_dir

    def observe(self, session: SessionSpec) -> list[Any]:
        return []


class _CountingExecutor(SessionExecutor):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
        name = str(session_ctx.get("task_name") or "")
        self.calls.append(name)
        return SessionOutcome(session_id=session.id, success=True, observation=f"live-{name}")


def _task(name: str) -> EvalTask:
    return EvalTask(
        name=name,
        sessions=[
            SessionSpec(id=1, instruction="s1", memory_inject=True),
            SessionSpec(id=2, instruction="s2", memory_inject=True),
        ],
    )


def test_checkpoint_roundtrip(tmp_path: Path) -> None:
    result = TaskExecution(
        task_id="alpha",
        task_name="alpha",
        memory_backend="stub",
        sessions=[SessionOutcome(session_id=1, success=True, observation="cached")],
    )
    path = save_task_result(tmp_path, result)
    assert path == task_checkpoint_path(tmp_path, "alpha")
    loaded = load_task_result(tmp_path, "alpha")
    assert loaded is not None
    assert loaded.task_name == "alpha"
    assert loaded.sessions[0].observation == "cached"


def test_missing_checkpoint_returns_none(tmp_path: Path) -> None:
    assert load_task_result(tmp_path, "nope") is None


@pytest.mark.asyncio
async def test_resume_skips_completed_tasks(tmp_path: Path) -> None:
    """已有 checkpoint 的 task 不重跑；缺失的 task 正常执行。"""
    cached = TaskExecution(
        task_id="done",
        task_name="done",
        memory_backend="stub",
        sessions=[SessionOutcome(session_id=1, success=True, observation="from-disk")],
    )
    save_task_result(tmp_path, cached)

    executor = _CountingExecutor()
    runner = ParallelTaskRunner(
        adapter_factory=lambda name: _StubAdapter(MemorySpec(name=name, type="directory")),
        executor=executor,
        output_dir=tmp_path,
        n_concurrent=2,
        resume=True,
    )
    results = await runner.run([_task("done"), _task("todo")])

    by_name = {r.task_name: r for r in results}
    assert by_name["done"].sessions[0].observation == "from-disk"
    assert by_name["todo"].sessions[0].observation == "live-todo"
    assert executor.calls == ["todo", "todo"]  # 两个 session，均来自未完成 task


@pytest.mark.asyncio
async def test_resume_binds_adapter_without_rerunning(tmp_path: Path) -> None:
    """resume 跳过时仍把 adapter 挂到 runner.adapters（Quality 读 memory 用）。"""
    cached = TaskExecution(
        task_id="done",
        task_name="done",
        memory_backend="stub",
        sessions=[SessionOutcome(session_id=1, success=True, observation="from-disk")],
    )
    save_task_result(tmp_path, cached)
    executor = _CountingExecutor()
    runner = ParallelTaskRunner(
        adapter_factory=lambda name: _StubAdapter(MemorySpec(name=name, type="directory")),
        executor=executor,
        output_dir=tmp_path,
        n_concurrent=1,
        resume=True,
    )
    await runner.run([_task("done")])
    assert "done" in runner.adapters
    assert executor.calls == []


@pytest.mark.asyncio
async def test_resume_off_reruns_everything(tmp_path: Path) -> None:
    cached = TaskExecution(
        task_id="done",
        task_name="done",
        memory_backend="stub",
        sessions=[SessionOutcome(session_id=1, success=True, observation="from-disk")],
    )
    save_task_result(tmp_path, cached)

    executor = _CountingExecutor()
    runner = ParallelTaskRunner(
        adapter_factory=lambda name: _StubAdapter(MemorySpec(name=name, type="directory")),
        executor=executor,
        output_dir=tmp_path,
        n_concurrent=1,
        resume=False,
    )
    results = await runner.run([_task("done")])
    assert results[0].sessions[0].observation == "live-done"
    assert "done" in executor.calls
