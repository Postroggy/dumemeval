"""测试：Trace 行为统计增强（tool call / LLM 次数 / 耗时 / 占比）。"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.metrics.dimensions.trace_stats import (
    DurationStats,
    LlmCallCounter,
    PhaseDurationStats,
    ToolCallCounter,
    TraceEnricher,
)
from dumemeval.models import (
    EvalTask,
    MetricReport,
    SessionOutcome,
    SessionSpec,
    TaskExecution,
    TaskResult,
    TraceResult,
)


def _make_step(
    source: str, ts: str, tool_calls: list[dict[str, Any]] | None = None, llm: int = 0
) -> dict[str, Any]:
    return {"source": source, "timestamp": ts, "tool_calls": tool_calls, "llm_call_count": llm}


def _trajectory(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "1.7", "steps": steps}


class TestStatCalculators:
    def test_tool_call_counter(self) -> None:
        traj = _trajectory(
            [
                _make_step("agent", "2026-09-01T00:00:00+00:00", tool_calls=[{"name": "search"}]),
                _make_step(
                    "agent", "2026-09-01T00:00:05+00:00", tool_calls=[{"name": "search"}, {"name": "click"}]
                ),
                _make_step("agent", "2026-09-01T00:00:10+00:00"),
            ]
        )
        out = ToolCallCounter().calculate(traj)
        assert out["total"] == 3
        assert out["by_tool"] == {"search": 2, "click": 1}

    def test_tool_call_empty_name_unknown(self) -> None:
        traj = _trajectory([_make_step("agent", "2026-09-01T00:00:00+00:00", tool_calls=[{}])])
        out = ToolCallCounter().calculate(traj)
        assert out["by_tool"] == {"unknown": 1}

    def test_llm_call_counter(self) -> None:
        traj = _trajectory(
            [
                _make_step("agent", "2026-09-01T00:00:00+00:00", llm=2),
                _make_step("tool", "2026-09-01T00:00:01+00:00"),
                _make_step("agent", "2026-09-01T00:00:02+00:00", llm=1),
            ]
        )
        assert LlmCallCounter().calculate(traj) == {"total": 3}

    def test_duration_seconds(self) -> None:
        traj = _trajectory(
            [
                _make_step("system", "2026-09-01T00:00:00+00:00"),
                _make_step("agent", "2026-09-01T00:00:30+00:00"),
            ]
        )
        out = DurationStats().calculate(traj)
        assert out["seconds"] == 30.0
        assert out["start"] == "2026-09-01T00:00:00+00:00"

    def test_duration_insufficient_timestamps(self) -> None:
        traj = _trajectory([_make_step("agent", "2026-09-01T00:00:00+00:00")])
        assert DurationStats().calculate(traj)["seconds"] is None

    def test_duration_invalid_iso_ignored(self) -> None:
        traj = _trajectory(
            [
                _make_step("agent", "not-a-date"),
                _make_step("agent", "2026-09-01T00:00:05+00:00"),
            ]
        )
        assert DurationStats().calculate(traj)["seconds"] is None

    def test_phase_duration_ratio(self) -> None:
        t0 = datetime.fromisoformat("2026-09-01T00:00:00+00:00")
        traj = _trajectory(
            [
                _make_step("agent", (t0 + timedelta(seconds=0)).isoformat()),
                _make_step("agent", (t0 + timedelta(seconds=5)).isoformat()),
                _make_step("tool", (t0 + timedelta(seconds=5)).isoformat()),
                _make_step("tool", (t0 + timedelta(seconds=15)).isoformat()),
            ]
        )
        out = PhaseDurationStats().calculate(traj)
        assert out["by_source"]["agent"] == round(5 / 15, 4)  # 0~5s
        assert out["by_source"]["tool"] == round(10 / 15, 4)  # 5~15s
        assert out["total_seconds"] == 15.0


class TestTraceEnricher:
    def _task_with_trial(self, tmp: Path, traj: dict[str, Any] | None) -> tuple[EvalTask, TaskResult]:
        trial = tmp / "trials" / "session_1"
        trial_dir = str(trial)
        if traj is not None:
            (trial / "agent").mkdir(parents=True)
            import json

            (trial / "agent" / "trajectory.json").write_text(json.dumps(traj))
        task = EvalTask(
            name="t",
            sessions=[SessionSpec(id=1, instruction="s1")],
        )
        result = TaskResult(
            task_id="t",
            task_name="t",
            execution=TaskExecution(
                task_id="t",
                task_name="t",
                memory_backend="m",
                sessions=[
                    SessionOutcome(session_id=1, success=True, observation="obs", trial_dir=trial_dir),
                ],
            ),
            metrics=MetricReport(trace=TraceResult()),
        )
        return task, result

    def test_enrich_writes_stats(self, tmp_path: Path) -> None:
        traj = _trajectory(
            [
                _make_step("system", "2026-09-01T00:00:00+00:00"),
                _make_step("agent", "2026-09-01T00:00:03+00:00", tool_calls=[{"name": "search"}], llm=1),
            ]
        )
        task, result = self._task_with_trial(tmp_path, traj)
        TraceEnricher().enrich(task, result)
        assert result.metrics is not None and result.metrics.trace is not None
        entry = result.metrics.trace.details[0]
        assert entry["stats_available"] is True
        assert entry["tool_calls"]["total"] == 1
        assert entry["llm_calls"]["total"] == 1
        assert entry["duration"]["seconds"] == 3.0
        assert "phase_duration" in entry

    def test_enrich_no_trajectory_marks_unavailable(self, tmp_path: Path) -> None:
        task, result = self._task_with_trial(tmp_path, None)
        TraceEnricher().enrich(task, result)
        assert result.metrics is not None and result.metrics.trace is not None
        entry = result.metrics.trace.details[0]
        assert entry["stats_available"] is False
        assert "tool_calls" not in entry

    def test_enrich_no_trial_dir_marks_unavailable(self) -> None:
        task = EvalTask(name="t", sessions=[SessionSpec(id=1, instruction="s1")])
        result = TaskResult(
            task_id="t",
            task_name="t",
            execution=TaskExecution(
                task_id="t",
                task_name="t",
                memory_backend="m",
                sessions=[
                    SessionOutcome(session_id=1, success=True, observation="obs", trial_dir=None),
                ],
            ),
            metrics=MetricReport(trace=TraceResult()),
        )
        TraceEnricher().enrich(task, result)
        assert result.metrics is not None and result.metrics.trace is not None
        assert result.metrics.trace.details[0]["stats_available"] is False
