"""Memory use requires storage or successful tool evidence, never prompt mentions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dumemeval.adapters.directory import DirectoryMemoryAdapter
from dumemeval.metrics import MetricInput, MetricsAggregator, TraceCalculator
from dumemeval.models import EvalTask, MemorySpec, SessionOutcome, SessionSpec, TaskExecution


def _read_step(path: str, *, failed: bool = False, call_id: str = "read1") -> dict:
    return {
        "source": "agent",
        "tool_calls": [{"tool_call_id": call_id, "function_name": "Read", "arguments": {"file_path": path}}],
        "observation": {
            "results": [
                {
                    "source_call_id": call_id,
                    "extra": {
                        "tool_result_metadata": {
                            "raw_tool_result": {"is_error": failed},
                            "tool_use_result": {
                                "type": "text",
                                "file": {"filePath": path, "content": "memory"},
                            },
                        }
                    },
                }
            ]
        },
    }


def _adapter(tmp_path: Path) -> tuple[DirectoryMemoryAdapter, EvalTask]:
    adapter = DirectoryMemoryAdapter(
        MemorySpec(name="directory", type="directory", path=str(tmp_path / "memory"))
    )
    task = EvalTask(
        name="task",
        sessions=[SessionSpec(id=1, instruction="solve"), SessionSpec(id=2, instruction="continue")],
    )
    adapter.setup(task)
    return adapter, task


def test_file_change_then_correlated_read_across_sessions(tmp_path: Path) -> None:
    adapter, task = _adapter(tmp_path)
    first, second = task.sessions
    adapter.inject(first, {})
    file = adapter.memory_dir / "notes.txt"
    file.write_text("first")
    file.write_text("final")  # Two writes collapse to one observed file change.
    adapter.observe_execution(first, SessionOutcome(session_id=1, success=True))
    adapter.snapshot(first, tmp_path / "snapshots")
    adapter.inject(second, {})
    trajectory = tmp_path / "trial/agent/trajectory.json"
    trajectory.parent.mkdir(parents=True)
    read = _read_step("/app/memory/notes.txt")
    trajectory.write_text(json.dumps({"steps": [read, read]}))
    outcome = SessionOutcome(session_id=2, success=True, trial_dir=str(trajectory.parents[1]))
    adapter.observe_execution(second, outcome)
    adapter.observe_execution(second, outcome)  # Observation retries cannot duplicate events.
    execution = TaskExecution(
        task_id="task", task_name="task", memory_backend="directory", memory_ops=adapter.all_ops()
    )
    report = MetricsAggregator([TraceCalculator()]).run(MetricInput(task=task, execution=execution))
    assert report.trace.memory_tool_used is True
    assert report.trace.memory_write_ops == report.trace.memory_read_ops == 1
    events = [op for op in adapter.all_ops() if op.source != "adapter"]
    assert [(e.session_id, e.source) for e in events] == [(1, "file_hash_change"), (2, "atif_read_result")]
    assert events[0].evidence["before_sha256"] is None
    assert len(events[0].evidence["after_sha256"]) == 64


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [_read_step("/app/memory/notes.txt", failed=True)],
        [_read_step("/app/memory-other/notes.txt")],
        [_read_step("/app/memory/../../secret")],
        [{"source": "user", "message": "I read /app/memory/notes.txt"}],
    ],
)
def test_missing_or_invalid_read_is_unmeasured(tmp_path: Path, steps: list[dict]) -> None:
    adapter, task = _adapter(tmp_path)
    session = task.sessions[0]
    adapter.inject(session, {})
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "agent/trajectory.json").write_text(json.dumps({"steps": steps}))
    adapter.observe_execution(session, SessionOutcome(session_id=1, success=True, trial_dir=str(trial)))
    execution = TaskExecution(
        task_id="task", task_name="task", memory_backend="directory", memory_ops=adapter.all_ops()
    )
    report = MetricsAggregator([TraceCalculator()]).run(MetricInput(task=task, execution=execution))
    assert report.trace.memory_tool_used is None
    assert report.trace.memory_write_ops is None
    assert report.trace.memory_read_ops is None
    assert "trace.memory_tool_used" not in report.flat


def test_missing_trajectory_keeps_observed_file_change(tmp_path: Path) -> None:
    adapter, task = _adapter(tmp_path)
    session = task.sessions[0]
    adapter.inject(session, {})
    (adapter.memory_dir / "note.txt").write_text("retained after failure")
    adapter.observe_execution(
        session, SessionOutcome(session_id=1, success=False, trial_dir=str(tmp_path / "absent"))
    )
    assert [op.op for op in adapter.observe(session)] == ["inject", "add"]
