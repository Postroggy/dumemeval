"""跨 task 断点续跑（已完成 task 的 TaskExecution 落盘 / 加载）。

粒度是 task：session 间有 memory 依赖，不能只跳过中间 session。
文件名按 task 名净化，原子写盘（temp + replace），避免半写 JSON。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from pathlib import Path

from ..models import TaskExecution

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_task_name(name: str) -> str:
    """task 名 → 文件系统安全段。"""
    safe = _UNSAFE.sub("_", name).strip("._-")
    return safe or "task"


def task_checkpoint_path(output_dir: str | Path, task_name: str) -> Path:
    """``<output>/checkpoints/<task>.json``。"""
    return Path(output_dir) / "checkpoints" / f"{sanitize_task_name(task_name)}.json"


def save_task_result(output_dir: str | Path, result: TaskExecution) -> Path:
    """原子写入 task 结果（供 ``--resume`` 跳过已完成 task）。"""
    path = task_checkpoint_path(output_dir, result.task_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.model_dump(mode="json")
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    return path


def load_task_result(output_dir: str | Path, task_name: str) -> TaskExecution | None:
    """读取已完成 task；缺失或损坏返回 None（调用方重跑）。"""
    path = task_checkpoint_path(output_dir, task_name)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        result = TaskExecution.model_validate(raw)
        return result if result.status == "completed" and all(s.success for s in result.sessions) else None
    except (OSError, json.JSONDecodeError, ValueError):
        return None
