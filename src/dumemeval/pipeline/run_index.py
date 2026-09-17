"""run 级结果索引：``index.json``（分析方取数地图，不管生命周期）。

设计（见 docs/architecture/run-artifacts.md）：
- 每个 task 列出 result/report 路径、session → trial_dir → trajectory 的映射、snapshots
- ``complete`` = 文件存在性（trial 目录 / trajectory 在不在），不是 session 成功
- 生命周期（checkpoints / lock）继续由原机制管，不折叠进来
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..models import EvalTask, TaskResult

# trail 内 ATIF trajectory 的相对路径（与 execution/harbor_bridge.py 同源约定）
TRAJECTORY_RELATIVE = "agent/trajectory.json"


def write_run_index(
    output_dir: str | Path,
    *,
    run_id: str,
    experiment_name: str,
    generated_at: str,
    tasks: list[EvalTask],
    results: Sequence[TaskResult],
) -> Path:
    """生成并落盘 ``index.json``，返回其路径。"""
    out = Path(output_dir)
    payload = {
        "run_id": run_id,
        "experiment_name": experiment_name,
        "generated_at": generated_at,
        "summary": "summary.json",
        "experiment_config": "experiment_config.json",
        "tasks": [_task_index(out, task, result) for task, result in zip(tasks, results, strict=True)],
    }
    path = out / "index.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _task_index(out: Path, task: EvalTask, result: TaskResult) -> dict[str, Any]:
    """单个 task 的索引条目。"""
    task_dir = out / f"{task.name}__{result.execution.memory_backend}"
    snapshots = (
        [str(p) for p in (out / "snapshots").glob(f"{result.execution.memory_backend}*")]
        if (out / "snapshots").exists()
        else []
    )

    sessions = []
    complete = True
    for rec in [r.model_dump() for r in result.execution.sessions]:
        trial_dir = rec.get("trial_dir")
        if not trial_dir:
            sessions.append({"session_id": rec.get("session_id"), "trial_dir": None, "complete": False})
            complete = False
            continue
        trial_path = Path(trial_dir)
        trajectory = trial_path / TRAJECTORY_RELATIVE
        has_trajectory = trajectory.exists()
        if not (trial_path.exists() and has_trajectory):
            complete = False
        sessions.append(
            {
                "session_id": rec.get("session_id"),
                "trial_dir": str(trial_path),
                "trajectory": str(trajectory),
                "complete": bool(has_trajectory),
            }
        )

    return {
        "name": task.name,
        "backend": result.execution.memory_backend,
        "result": str(task_dir / "result.json"),
        "report": str(task_dir / "report.md"),
        "sessions": sessions,
        "snapshots": snapshots,
        "complete": complete,
    }
