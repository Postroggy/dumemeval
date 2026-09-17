"""目录型 Memory 适配器：内存型 memory 统一为目录语义。

适用场景：
- Claude Code 内置 memory（CLAUDE.md / auto-memory 目录）
- 外挂本地目录型 memory 插件

设计要点：
- host 侧维护 memory 目录（`spec.path`），inject 时声明为挂载（见 base.declare_mount）
- Quality 观测 = 分析目录内容（对比 ground truth）+ 记录注入/快照操作
- 跨 session 保留 = 目录不销毁，session 间快照
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Any

from ..models import EvalTask, MemoryOp, MemorySpec, SessionOutcome, SessionSpec
from .base import BaseMemoryAdapter, declare_mount
from .registry import register_adapter

# agent 环境内的 memory 目录（与 lifecycle.memory_transfer 的传递目标一致）
CONTAINER_MEMORY_DIR = "/app/memory"


@register_adapter
class DirectoryMemoryAdapter(BaseMemoryAdapter):
    """目录型 memory 后端。"""

    type_name = "directory"

    def __init__(self, spec: MemorySpec) -> None:
        super().__init__(spec)
        # 路径在构造时绑定：resume 跳过 setup（setup 会清空目录）时仍能 read_memory_files
        self.memory_dir = Path(spec.path) if spec.path else Path("results") / "memory" / spec.name
        self._before: dict[str, str] = {}
        self._observed: set[int] = set()

    def setup(self, task: EvalTask) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        # 清空重建，保证干净起点（上一次 run 的残留会污染 Quality）
        if any(self.memory_dir.iterdir()):
            for item in self.memory_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        self._ops.clear()
        self._observed.clear()
        self._record("setup", 0)

    def inject(self, session: SessionSpec, session_ctx: dict[str, Any]) -> None:
        """把 memory 目录声明为 agent 环境内的挂载。

        之前的实现依赖 ``session_ctx["agent_memory_target"]``，但没有任何执行器
        设置该键——注入永远静默跳过。现在统一走 ``memory_mounts`` 契约，
        执行器（Harbor bind mount / Mock 清单）都会消费。
        """
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._before = self._file_hashes()
        declare_mount(session_ctx, self.memory_dir, CONTAINER_MEMORY_DIR)
        env = session_ctx.setdefault("agent_env", {})
        env["DUMEMEVAL_MEMORY_DIR"] = CONTAINER_MEMORY_DIR
        n_items = len(list(self.memory_dir.iterdir()))
        self._record(
            "inject",
            session.id,
            content=f"mount {self.memory_dir} -> {CONTAINER_MEMORY_DIR}（{n_items} 项）",
        )

    def memory_usage_hint(self) -> str | None:
        return f"持久记忆目录：{CONTAINER_MEMORY_DIR}（env DUMEMEVAL_MEMORY_DIR）"

    def snapshot(self, session: SessionSpec, snapshot_dir: Path) -> Path:
        """快照 memory 目录到 snapshot_dir/session_{id}/。"""
        snap = snapshot_dir / f"session_{session.id}"
        snap.mkdir(parents=True, exist_ok=True)
        for item in self.memory_dir.iterdir():
            dst = snap / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
        self._record("snapshot", session.id, content=str(snap))
        return snap

    def observe(self, session: SessionSpec) -> list[MemoryOp]:
        """目录型：返回本 session 期间记录的 ops。"""
        return [op for op in self._ops if op.session_id == session.id]

    def _file_hashes(self) -> dict[str, str]:
        hashes = {}
        for path in sorted(self.memory_dir.rglob("*")):
            if path.is_file() and not path.is_symlink():
                with path.open("rb") as handle:
                    hashes[path.relative_to(self.memory_dir).as_posix()] = hashlib.file_digest(
                        handle, "sha256"
                    ).hexdigest()
        return hashes

    def observe_execution(self, session: SessionSpec, outcome: SessionOutcome) -> None:
        """Record changed files and successful structured reads, without replaying tools.

        Changes are a lower bound on writes: multiple writes to one file collapse,
        and write-then-restore is invisible. Shell commands are deliberately not parsed.
        """
        if session.id in self._observed:
            return
        self._observed.add(session.id)
        try:
            after = self._file_hashes()
        except OSError:
            self._record("observation_unavailable", session.id, "Could not hash memory files")
        else:
            for name in sorted(self._before.keys() | after.keys()):
                old, new = self._before.get(name), after.get(name)
                if old == new:
                    continue
                self._ops.append(
                    MemoryOp(
                        session_id=session.id,
                        op="remove" if new is None else "replace" if old is not None else "add",
                        timestamp=time.time(),
                        source="file_hash_change",
                        evidence={"path": name, "before_sha256": old, "after_sha256": new},
                    )
                )
        if outcome.trial_dir:
            try:
                self._observe_reads(session, Path(outcome.trial_dir) / "agent/trajectory.json")
            except (AttributeError, TypeError):
                self._record("observation_unavailable", session.id, "Unsupported trajectory structure")

    def _observe_reads(self, session: SessionSpec, path: Path) -> None:
        try:
            trajectory = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(trajectory, dict) or not isinstance(trajectory.get("steps"), list):
            return
        seen: set[str] = set()
        for step in trajectory["steps"]:
            if not isinstance(step, dict) or step.get("source") != "agent":
                continue
            results = (step.get("observation") or {}).get("results", [])
            for call in step.get("tool_calls") or []:
                call_id = call.get("tool_call_id")
                if call.get("function_name") != "Read" or not call_id or call_id in seen:
                    continue
                target = self._memory_path((call.get("arguments") or {}).get("file_path"))
                if target is None:
                    continue
                for result in results:
                    if result.get("source_call_id") != call_id:
                        continue
                    metadata = (result.get("extra") or {}).get("tool_result_metadata") or {}
                    raw = metadata.get("raw_tool_result") or {}
                    payload = metadata.get("tool_use_result") or {}
                    file = payload.get("file") or {}
                    if (
                        raw.get("is_error")
                        or payload.get("type") != "text"
                        or "content" not in file
                        or self._memory_path(file.get("filePath")) != target
                    ):
                        continue
                    self._ops.append(
                        MemoryOp(
                            session_id=session.id,
                            op="search",
                            timestamp=time.time(),
                            source="atif_read_result",
                            evidence={
                                "path": target,
                                "tool_call_id": call_id,
                                "trajectory": str(path),
                                "observed_at": step.get("timestamp"),
                            },
                        )
                    )
                    seen.add(call_id)
                    break

    @staticmethod
    def _memory_path(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        path = PurePosixPath(posixpath.normpath(value))
        if not path.is_relative_to(CONTAINER_MEMORY_DIR) or str(path) == CONTAINER_MEMORY_DIR:
            return None
        return path.relative_to(CONTAINER_MEMORY_DIR).as_posix()

    def read_memory_files(self) -> dict[str, str]:
        """读取 memory 目录全部文件内容（Quality 评测用）。"""
        import contextlib

        result: dict[str, str] = {}
        if not self.memory_dir.exists():
            return result
        for path in sorted(self.memory_dir.rglob("*")):
            if path.is_file():
                with contextlib.suppress(OSError):
                    result[str(path.relative_to(self.memory_dir))] = path.read_text()
        return result
