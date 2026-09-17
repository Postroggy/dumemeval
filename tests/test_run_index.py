"""测试：run_id 派生 + index.json 结果索引（docs/architecture/run-artifacts.md）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.config import load_config
from dumemeval.models import EvalTask, SessionOutcome, SessionSpec, TaskExecution, TaskResult
from dumemeval.pipeline.run_index import write_run_index
from dumemeval.provenance import derive_run_id


def _cfg(tmp_path: Path, *, memory_type: str = "directory", name: str = "demo") -> Path:
    p = tmp_path / f"{name}_{memory_type}.yaml"
    p.write_text(
        f"""
experiment:
  name: {name}
  protocol: memory_session_transfer
memory:
  name: m
  type: {memory_type}
task:
  benchmark: locomo
  memory_instruction: proactive
  data:
    type: local
    name: locomo_smoke
  sessions:
    - instruction: "占位"
      placeholder: true
    - instruction: "占位"
      placeholder: true
agent:
  runtime: claude-code
"""
    )
    return p


class TestDeriveRunId:
    def test_stable_across_same_config(self, tmp_path: Path) -> None:
        cfg = load_config(_cfg(tmp_path))
        assert derive_run_id(cfg) == derive_run_id(cfg)

    def test_differs_when_memory_changes(self, tmp_path: Path) -> None:
        a = derive_run_id(load_config(_cfg(tmp_path, memory_type="directory")))
        b = derive_run_id(load_config(_cfg(tmp_path, memory_type="none")))
        assert a != b

    def test_slug_readable(self, tmp_path: Path) -> None:
        rid = derive_run_id(load_config(_cfg(tmp_path)))
        assert "locomo" in rid
        assert "memory_session_transfer" in rid
        assert "directory" in rid


class TestWriteRunIndex:
    def _results(self, tmp_path: Path, *, with_trial: bool) -> tuple[list[EvalTask], list[TaskResult]]:
        tasks = [
            EvalTask(
                name="t0",
                sessions=[SessionSpec(id=1, instruction="s1"), SessionSpec(id=2, instruction="s2")],
                benchmark="locomo",
            )
        ]
        sessions: list[SessionOutcome] = []
        for sid in (1, 2):
            trial_dir = None
            if with_trial:
                trial = tmp_path / f"trials/dumemeval_t0__session_{sid}"
                (trial / "agent").mkdir(parents=True, exist_ok=True)
                (trial / "agent" / "trajectory.json").write_text("{}")
                trial_dir = str(trial)
            sessions.append(
                SessionOutcome(
                    session_id=sid,
                    success=True,
                    observation="obs",
                    tokens_in=10,
                    tokens_out=5,
                    trial_dir=trial_dir,
                )
            )
        results = [
            TaskResult(
                task_id="t0",
                task_name="t0",
                execution=TaskExecution(
                    task_id="t0",
                    task_name="t0",
                    memory_backend="directory-m",
                    sessions=sessions,
                ),
            )
        ]
        return tasks, results

    def test_index_marks_complete_with_trials(self, tmp_path: Path) -> None:
        tasks, results = self._results(tmp_path, with_trial=True)
        out = tmp_path / "out"
        out.mkdir(parents=True)
        path = write_run_index(
            out, run_id="rid-1", experiment_name="demo", generated_at="t", tasks=tasks, results=results
        )
        index = json.loads(path.read_text())
        assert index["run_id"] == "rid-1"
        task = index["tasks"][0]
        assert task["complete"] is True
        assert all(s["complete"] for s in task["sessions"])
        assert task["sessions"][0]["trajectory"].endswith("agent/trajectory.json")

    def test_index_marks_incomplete_without_trials(self, tmp_path: Path) -> None:
        tasks, results = self._results(tmp_path, with_trial=False)
        out = tmp_path / "out2"
        out.mkdir(parents=True)
        path = write_run_index(
            out, run_id="rid-2", experiment_name="demo", generated_at="t", tasks=tasks, results=results
        )
        index = json.loads(path.read_text())
        assert index["tasks"][0]["complete"] is False
