"""测试：none memory adapter（无 memory baseline 表达，docs/architecture/run-artifacts.md）。"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.adapters.registry import adapter_names, create_adapter
from dumemeval.models import EvalTask, MemorySpec, SessionSpec


def _task() -> EvalTask:
    return EvalTask(
        name="none-task",
        sessions=[
            SessionSpec(id=1, instruction="记住偏好", memory_inject=True),
            SessionSpec(id=2, instruction="应用偏好", memory_inject=True),
        ],
    )


def _spec(tmp_path: Path) -> MemorySpec:
    return MemorySpec(name="none-baseline", type="none", path=str(tmp_path / "mem"))


class TestNoneAdapter:
    def test_registered(self) -> None:
        assert "none" in adapter_names()

    def test_lifecycle_noop(self, tmp_path: Path) -> None:
        """setup/inject/snapshot/observe 全部 no-op，不产生 ops。"""
        adapter = create_adapter(_spec(tmp_path))
        task = _task()
        adapter.setup(task)
        adapter.seed_history(task)

        session_ctx: dict[str, Any] = {"agent_env": {}}
        adapter.inject(task.sessions[0], session_ctx)
        # 无 memory：不写任何注入通道（这是语义本意）
        assert not session_ctx.get("memory_mounts")
        assert not session_ctx.get("agent_env")

        snap = adapter.snapshot(task.sessions[0], tmp_path / "snaps")
        assert snap.exists()
        assert adapter.observe(task.sessions[0]) == []
        assert adapter.memory_usage_hint() is None
        assert adapter.all_ops() == []

    def test_usable_in_mock_run(self, tmp_path: Path) -> None:
        """none adapter 可正常跑一次 mock 评测（baseline 表达）。"""
        from dumemeval.cli import main

        cfg = tmp_path / "none.yaml"
        cfg.write_text(
            f"""
experiment:
  name: none-baseline
memory:
  name: none-base
  type: none
task:
  sessions:
    - instruction: "s1"
    - instruction: "s2"
judging:
  type: rule
execution:
  engine: mock
output:
  dir: {tmp_path / "res"}
  tasks_dir: {tmp_path / "tasks"}
"""
        )
        rc = main(["run", "--config", str(cfg), "--mock", "--output", str(tmp_path / "res")])
        assert rc == 0
        summary = (tmp_path / "res" / "summary.json").read_text()
        assert '"run_id"' in summary
        assert (tmp_path / "res" / "index.json").exists()
