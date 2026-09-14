"""ParallelTaskRunner 测试：并行度 / 保序 / task 隔离 / 失败隔离。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from dumemeval.adapters.base import BaseMemoryAdapter
from dumemeval.execution.executor import SessionExecutor, SessionOutcome
from dumemeval.lifecycle.parallel import ParallelTaskRunner
from dumemeval.models import EvalTask, MemorySpec, SessionSpec


class _StubAdapter(BaseMemoryAdapter):
    """记录 task 名（memory path 隔离验证用）。"""

    def __init__(self, spec: MemorySpec):
        super().__init__(spec)
        self.task_name_seen: str | None = None

    def setup(self, task: EvalTask) -> None:
        self.task_name_seen = task.name

    def inject(self, session: SessionSpec, session_ctx: dict[str, Any]) -> None:
        session_ctx["agent_env"] = {"stub": self.name}

    def snapshot(self, session: SessionSpec, snapshot_dir: Path) -> Path:
        return snapshot_dir

    def observe(self, session: SessionSpec) -> list[Any]:
        return []


class _ConcurrencyProbeExecutor(SessionExecutor):
    """记录并发峰值与收到的 task_name。"""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.running = 0
        self.peak = 0
        self.task_names: list[str] = []

    async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
        self.task_names.append(str(session_ctx.get("task_name")))
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(self.delay)
            return SessionOutcome(session_id=session.id, success=True, observation=f"ok-{session.id}")
        finally:
            self.running -= 1


def _task(name: str, n_sessions: int = 2) -> EvalTask:
    return EvalTask(
        name=name,
        sessions=[
            SessionSpec(id=i + 1, instruction=f"instr {i + 1}", memory_inject=True) for i in range(n_sessions)
        ],
    )


@pytest.mark.asyncio
async def test_parallel_runs_tasks_concurrently(tmp_path: Path) -> None:
    """n_concurrent=3 时并发峰值 > 1（真正并行，不是串行循环）。"""
    executor = _ConcurrencyProbeExecutor()
    runner = ParallelTaskRunner(
        adapter_factory=lambda name: _StubAdapter(MemorySpec(name=name, type="directory")),
        executor=executor,
        output_dir=tmp_path,
        n_concurrent=3,
    )
    results = await runner.run([_task(f"t{i}") for i in range(3)])

    assert executor.peak > 1
    assert len(results) == 3


@pytest.mark.asyncio
async def test_semaphore_bounds_concurrency(tmp_path: Path) -> None:
    """并发峰值不超过 n_concurrent（信号量限流）。"""
    executor = _ConcurrencyProbeExecutor()
    runner = ParallelTaskRunner(
        adapter_factory=lambda name: _StubAdapter(MemorySpec(name=name, type="directory")),
        executor=executor,
        output_dir=tmp_path,
        n_concurrent=2,
    )
    await runner.run([_task(f"t{i}") for i in range(6)])
    assert executor.peak <= 2


@pytest.mark.asyncio
async def test_results_preserve_task_order(tmp_path: Path) -> None:
    """结果列表与输入 tasks 顺序对齐（即使完成顺序乱）。"""
    executor = _ConcurrencyProbeExecutor(delay=0.02)
    runner = ParallelTaskRunner(
        adapter_factory=lambda name: _StubAdapter(MemorySpec(name=name, type="directory")),
        executor=executor,
        output_dir=tmp_path,
        n_concurrent=4,
    )
    tasks = [_task(f"task_{i}") for i in range(4)]
    results = await runner.run(tasks)
    assert [r.task_name for r in results] == [t.name for t in tasks]


@pytest.mark.asyncio
async def test_adapters_isolated_per_task(tmp_path: Path) -> None:
    """per-task adapter 实例 + executor 收到正确 task_name（隔离验证）。"""
    executor = _ConcurrencyProbeExecutor()
    runner = ParallelTaskRunner(
        adapter_factory=lambda name: _StubAdapter(MemorySpec(name=name, type="directory")),
        executor=executor,
        output_dir=tmp_path,
        n_concurrent=3,
    )
    tasks = [_task("alpha"), _task("beta")]
    await runner.run(tasks)

    assert set(runner.adapters) == {"alpha", "beta"}
    assert runner.adapters["alpha"] is not runner.adapters["beta"]
    # SessionRunner 把 task.name 放进 session_ctx，executor 应看到
    assert set(executor.task_names) == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_single_task_failure_does_not_abort_batch(tmp_path: Path) -> None:
    """一个 task 编排失败 → 转成带 error 的结果，其余 task 正常完成。"""

    def _factory(name: str) -> BaseMemoryAdapter:
        if name == "bad":
            raise RuntimeError("adapter init boom")
        return _StubAdapter(MemorySpec(name=name, type="directory"))

    executor = _ConcurrencyProbeExecutor()
    runner = ParallelTaskRunner(
        adapter_factory=_factory, executor=executor, output_dir=tmp_path, n_concurrent=3
    )
    results = await runner.run([_task("good1"), _task("bad"), _task("good2")])

    by_name = {r.task_name: r for r in results}
    assert by_name["good1"].sessions[0].success
    assert by_name["good2"].sessions[0].success
    failed = by_name["bad"]
    assert failed.sessions[0].session_id >= 1
    assert "RuntimeError" in str(failed.sessions[0].error)


@pytest.mark.asyncio
async def test_single_task_degenerates_to_sequential(tmp_path: Path) -> None:
    """n_concurrent=1 / 单 task：退化为原串行行为（等价旧路径）。"""
    executor = _ConcurrencyProbeExecutor()
    runner = ParallelTaskRunner(
        adapter_factory=lambda name: _StubAdapter(MemorySpec(name=name, type="directory")),
        executor=executor,
        output_dir=tmp_path,
        n_concurrent=1,
    )
    results = await runner.run([_task("solo")])
    assert len(results) == 1
    assert executor.peak == 1


def test_invalid_n_concurrent_rejected() -> None:
    with pytest.raises(ValueError, match="n_concurrent"):
        ParallelTaskRunner(
            adapter_factory=lambda name: _StubAdapter(MemorySpec(name=name, type="directory")),
            executor=_ConcurrencyProbeExecutor(),
            n_concurrent=0,
        )


# ── finalize_run：多 task 指标聚合（pooled benchmark）───────────────────────


def _locomo_task(name: str, answer_pred: str) -> EvalTask:
    return EvalTask(
        name=name,
        sessions=[SessionSpec(id=1, instruction="qa", memory_inject=True)],
        data={
            "benchmark": "locomo",
            "qa": [{"question": "Where did they first meet?", "answer": "Paris", "category": 4}],
        },
        benchmark="locomo",
    )


def _result_for(task: EvalTask, observation: str) -> Any:
    from dumemeval.models import EvalResult

    return EvalResult(
        task_name=task.name,
        memory_backend="stub",
        session_outcomes=[{"session_id": 1, "success": True, "observation": observation, "query": None}],
    )


def test_finalize_run_pools_benchmark_across_tasks(tmp_path: Path) -> None:
    """两个 task 各 1 题：一个答对（f1=1）一个答错（f1=0）→ pooled f1=0.5。"""
    from dumemeval.core.config import ExperimentConfig
    from dumemeval.pipeline import finalize_run

    cfg = ExperimentConfig.model_validate(
        {
            "experiment": {"name": "parallel-test"},
            "memory": {"name": "stub-mem"},
            "task": {"sessions": [{"instruction": "placeholder"}, {"instruction": "placeholder"}]},
        }
    )
    task_a, task_b = _locomo_task("locomo_0", "Paris"), _locomo_task("locomo_1", "Paris")
    # A 精确命中（token F1=1.0）；B 完全跑题（0.0）→ pooled 0.5
    result_a = _result_for(task_a, "Paris")
    result_b = _result_for(task_b, "Totally unrelated answer.")

    def _rule(pred: str, gold: str, question: str) -> bool:
        return gold.lower() in pred.lower()

    summary = finalize_run(
        cfg,
        [task_a, task_b],
        [result_a, result_b],
        adapters={},
        output_dir=tmp_path,
        n_concurrent=2,
        mock=True,
        rule_judge=_rule,
    )

    assert summary.n_tasks == 2
    assert summary.benchmark is not None
    assert summary.benchmark.benchmark == "locomo"
    assert summary.benchmark.values["f1"] == pytest.approx(0.5)
    assert summary.benchmark.values["accuracy"] == pytest.approx(0.5)
    # accuracy 是 judge 判的：A 对 B 错
    assert summary.benchmark.values["accuracy_single_hop"] == pytest.approx(0.5)
    # 无 ground truth → quality 不算（None 而非伪 0）
    assert summary.quality_recall_avg is None
    # per-task 报告已生成
    assert len(summary.per_task) == 2
    assert all(Path(t.report_dir).exists() for t in summary.per_task)
    # 整批汇总落盘（pooled 表 + per-task 一览）
    summary_md = (tmp_path / "summary.md").read_text()
    summary_json = json.loads((tmp_path / "summary.json").read_text())
    assert "Benchmark[locomo]" in summary_md and "locomo_0 | 1/1" in summary_md
    assert summary_json["n_tasks"] == 2
    assert summary_json["benchmark"]["values"]["f1"] == pytest.approx(0.5)
    assert summary.experiment_name == "parallel-test"
