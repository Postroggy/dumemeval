"""跨 session memory 传递（lifecycle 核心职责）。

设计要点：
- 从 HarborBridge 抽出：memory 转移属于生命周期，不属于执行层
- collect：从 trial 目录收集 claude 写入的 auto-memory
- inject：把收集的 memory 复制到 bind mount 源目录（容器内可见）
- 单向依赖：只依赖 models（不依赖 execution）
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from ..models import SessionSpec

logger = logging.getLogger(__name__)

# 容器内 memory 目录（memory 传递路径，归属 lifecycle）
CONTAINER_MEMORY_TARGET = "/app/memory"

# 默认路径（可配置）
DEFAULT_MEMORY_TRANSFER_DIR = Path("results") / "memory" / "transfer"
DEFAULT_MOUNT_SOURCE = Path("results") / "memory" / "directory-demo"


class MemoryTransfer:
    """跨 session memory 传递管理器。

    用法（由 SessionRunner 编排）：
        transfer = MemoryTransfer(transfer_dir, mount_source)
        transfer.collect(trial_dir, session)   # session 后收集
        transfer.inject(session_ctx)            # 下个 session 前注入
    """

    def __init__(
        self,
        transfer_dir: Path | None = None,
        mount_source: Path | None = None,
    ):
        self.transfer_dir = transfer_dir or DEFAULT_MEMORY_TRANSFER_DIR
        self.mount_source = mount_source or DEFAULT_MOUNT_SOURCE

    # ── 收集（session 后）───────────────────────────────────────────────

    def collect(self, trial_dir: Path, session: SessionSpec) -> int:
        """从 trial 目录收集 claude 写入的 auto-memory。

        claude 的 memory 写在 $CLAUDE_CONFIG_DIR/projects/<cwd-slug>/memory/
        （Harbor 的 CLAUDE_CONFIG_DIR = /logs/agent/sessions，trial 结束后
        下载到 trial_dir/agent/sessions/）。

        Returns:
            int: 收集的文件数
        """
        dest = self.transfer_dir
        dest.mkdir(parents=True, exist_ok=True)

        memory_roots = [
            trial_dir / "agent" / "sessions" / "projects",
            trial_dir / "agent" / "sessions",
        ]
        copied = 0
        for root in memory_roots:
            if not root.exists():
                continue
            for proj in root.glob("*/memory/*"):
                if proj.is_file():
                    try:
                        # 用项目 slug + 文件名避免冲突
                        target = dest / f"{proj.parent.parent.name}__{proj.name}"
                        target.write_text(proj.read_text())
                        copied += 1
                    except OSError as e:
                        # 不静默：失败计入日志（调用方可决定是否告警）
                        logger.warning("收集失败 %s: %s", proj, e)
        if copied:
            logger.info("收集 %d 个 memory 文件 → %s", copied, dest)
        return copied

    # ── 注入（下个 session 前）─────────────────────────────────────────

    def inject(self, session_ctx: dict[str, Any]) -> str | None:
        """把跨 session 传递的 memory 复制到 bind mount 源目录。

        Args:
            session_ctx: 跨 session 上下文（含 memory_transfer_dir）

        Returns:
            str | None: 容器内 memory 目录路径（/app/memory），无注入时 None
        """
        transfer_dir = session_ctx.get("memory_transfer_dir")
        if transfer_dir is None:
            return None
        src = Path(transfer_dir)
        if not src.exists() or not any(src.iterdir()):
            return None

        mount_src = self.mount_source
        mount_src.mkdir(parents=True, exist_ok=True)

        copied = 0
        for f in src.iterdir():
            if f.is_file():
                try:
                    shutil.copy2(f, mount_src / f.name)
                    copied += 1
                except OSError as e:
                    logger.warning("注入失败 %s: %s", f, e)
        if copied:
            logger.info("注入 %d 个 memory 文件 → %s", copied, mount_src)
        return CONTAINER_MEMORY_TARGET
