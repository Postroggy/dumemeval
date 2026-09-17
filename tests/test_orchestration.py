"""测试：编排层（SessionRunner + MockRunner + TaskDirGenerator）。"""

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.adapters.directory import DirectoryMemoryAdapter
from dumemeval.execution.executor import SessionOutcome
from dumemeval.execution.mock import MockRunner
from dumemeval.execution.task_dir import TaskDirGenerator
from dumemeval.lifecycle.memory_transfer import MemoryTransfer
from dumemeval.lifecycle.runner import SessionRunner
from dumemeval.models import EvalTask, MemorySpec, SessionSpec, VerifierSpec


@pytest.fixture
def task() -> EvalTask:
    return EvalTask(
        name="test-task",
        sessions=[
            SessionSpec(id=1, instruction="session 1", verifier=VerifierSpec(type="rule")),
            SessionSpec(id=2, instruction="session 2", verifier=VerifierSpec(type="rule")),
        ],
    )


def _make_adapter(tmp_path: Path) -> DirectoryMemoryAdapter:
    return DirectoryMemoryAdapter(
        MemorySpec(name="test-mem", type="directory", path=str(tmp_path / "memory"))
    )


class TestSessionRunner:
    @pytest.mark.asyncio
    async def test_mock_run(self, task: EvalTask, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        runner = SessionRunner(
            adapter=adapter,
            executor=MockRunner(),
            snapshot_dir=tmp_path / "results",
            memory_transfer=MemoryTransfer(
                transfer_dir=tmp_path / "transfer", mount_source=tmp_path / "mount"
            ),
        )
        result = await runner.run(task)

        assert result.task_name == "test-task"
        assert len(result.sessions) == 2
        assert all(session.success for session in result.sessions)
        assert all(session.observation for session in result.sessions)
        from dumemeval.metrics.core.base import MetricInput
        from dumemeval.metrics.dimensions.utility import UtilityEvaluator

        bundle = UtilityEvaluator().calculate(MetricInput(execution=result))
        assert bundle.values["task_success"] == 1.0
        assert bundle.values["turns"] == 2.0
        assert bundle.values["success_rate"] == 1.0
        # memory ops 应包含 setup + inject + snapshot
        ops = result.memory_ops
        assert any(op.op == "setup" for op in ops)
        assert any(op.op == "inject" for op in ops)
        assert any(op.op == "snapshot" for op in ops)

    @pytest.mark.asyncio
    async def test_mock_run_hooks(self, task: EvalTask, tmp_path: Path) -> None:
        """验证生命周期事件钩子触发。"""
        from dumemeval.lifecycle.hooks import LifecycleEvent, LifecycleHooks

        adapter = _make_adapter(tmp_path)
        hooks = LifecycleHooks()
        events: list[str] = []

        async def _on_event(event: str, session: SessionSpec, ctx: dict[str, Any]) -> None:
            events.append(str(event))

        for ev in LifecycleEvent:
            hooks.on(ev, _on_event)

        runner = SessionRunner(
            adapter=adapter,
            executor=MockRunner(),
            snapshot_dir=tmp_path / "results",
            memory_transfer=MemoryTransfer(
                transfer_dir=tmp_path / "transfer", mount_source=tmp_path / "mount"
            ),
            hooks=hooks,
        )
        await runner.run(task)

        assert LifecycleEvent.EVAL_START.value in events
        assert LifecycleEvent.SESSION_START.value in events
        assert LifecycleEvent.SESSION_END.value in events
        assert LifecycleEvent.EVAL_END.value in events


class TestTaskDirGenerator:
    def test_generate_structure(self, tmp_path: Path) -> None:
        gen = TaskDirGenerator(tasks_root=str(tmp_path / "tasks"))
        session = SessionSpec(id=1, instruction="记住偏好", verifier=VerifierSpec(type="rule"))
        task_dir = gen.generate(session, "demo")

        assert (task_dir / "instruction.md").read_text() == "记住偏好"
        assert (task_dir / "task.toml").exists()
        assert (task_dir / "tests" / "test.sh").exists()
        assert (task_dir / "tests" / "verifier.py").exists()
        assert (task_dir / "environment" / "Dockerfile").exists()
        # test.sh 可执行
        assert (task_dir / "tests" / "test.sh").stat().st_mode & 0o111

    def test_generate_llm_judge_verifier(self, tmp_path: Path) -> None:
        from dumemeval.models import VerifierSpec

        gen = TaskDirGenerator(tasks_root=str(tmp_path / "tasks"))
        session = SessionSpec(id=1, instruction="x", verifier=VerifierSpec(type="llm_judge"))
        task_dir = gen.generate(session, "demo")
        verifier_src = (task_dir / "tests" / "verifier.py").read_text()
        assert "OpenAI()" in verifier_src

    def test_generated_verifier_syntax_ok(self, tmp_path: Path) -> None:
        """生成的 verifier 脚本应能通过语法编译。"""
        import py_compile

        gen = TaskDirGenerator(tasks_root=str(tmp_path / "tasks"))
        for vtype in ("rule", "llm_judge"):
            session = SessionSpec(id=1, instruction="x", verifier=VerifierSpec(type=vtype))
            task_dir = gen.generate(session, f"demo-{vtype}")
            py_compile.compile(str(task_dir / "tests" / "verifier.py"), doraise=True)


class TestProtocolIntegration:
    @pytest.mark.asyncio
    async def test_test_only_no_memory_ops(self, task: EvalTask, tmp_path: Path) -> None:
        """test_only 协议：所有 memory 生命周期通道关闭。"""
        from dumemeval.core.protocol import TestOnlyProtocol

        adapter = _make_adapter(tmp_path)
        runner = SessionRunner(
            adapter=adapter,
            executor=MockRunner(),
            protocol=TestOnlyProtocol(),
            snapshot_dir=tmp_path / "results",
            memory_transfer=MemoryTransfer(
                transfer_dir=tmp_path / "transfer", mount_source=tmp_path / "mount"
            ),
        )
        # test_only 要求 memory_inject=false
        task.sessions[0].memory_inject = False
        task.sessions[1].memory_inject = False
        result = await runner.run(task)

        # memory_ops 应无 inject/snapshot（协议关闭通道）
        ops = result.memory_ops
        assert not any(op.op == "inject" for op in ops)
        assert not any(op.op == "snapshot" for op in ops)

    @pytest.mark.asyncio
    async def test_mock_memory_transfer_collects_when_trial_dir_emitted(
        self, task: EvalTask, tmp_path: Path
    ) -> None:
        """mock 产出 trial_dir 后，SessionRunner 应走 MemoryTransfer.collect。"""
        transfer_dir = tmp_path / "transfer"
        trial = tmp_path / "trial"
        mem_src = trial / "agent" / "sessions" / "projects" / "slug" / "memory"
        mem_src.mkdir(parents=True)
        (mem_src / "MEMORY.md").write_text("Alice likes latte")

        class TransferMock(MockRunner):
            async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
                session_ctx["mock_trial_dir"] = trial
                return await super().run_session(session, session_ctx)

        adapter = _make_adapter(tmp_path)
        runner = SessionRunner(
            adapter=adapter,
            executor=TransferMock(),
            snapshot_dir=tmp_path / "results",
            memory_transfer=MemoryTransfer(transfer_dir=transfer_dir, mount_source=tmp_path / "mount"),
        )
        await runner.run(task)
        copied = list(transfer_dir.glob("*MEMORY.md"))
        assert copied, "mock trial_dir 应被 collect 进 transfer_dir"

    @pytest.mark.asyncio
    async def test_executor_error_emits_error_event(self, task: EvalTask, tmp_path: Path) -> None:
        """executor 抛异常 → ERROR 事件 + outcome 标记失败。"""
        from dumemeval.lifecycle.hooks import LifecycleEvent, LifecycleHooks

        class FailingExecutor(MockRunner):
            async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
                raise RuntimeError("boom")

        adapter = _make_adapter(tmp_path)
        hooks = LifecycleHooks()
        errors: list[str] = []

        async def _on_error(event: str, session: SessionSpec, ctx: dict[str, Any]) -> None:
            errors.append(str(event))

        hooks.on(LifecycleEvent.ERROR, _on_error)

        runner = SessionRunner(
            adapter=adapter,
            executor=FailingExecutor(),
            snapshot_dir=tmp_path / "results",
            memory_transfer=MemoryTransfer(
                transfer_dir=tmp_path / "transfer", mount_source=tmp_path / "mount"
            ),
            hooks=hooks,
        )
        result = await runner.run(task)

        assert errors == ["error"] * 2  # 两个 session 各触发一次
        assert not any(session.success for session in result.sessions)
        from dumemeval.metrics.core.base import MetricInput
        from dumemeval.metrics.dimensions.utility import UtilityEvaluator

        bundle = UtilityEvaluator().calculate(MetricInput(execution=result))
        assert bundle.values["task_success"] == 0.0
