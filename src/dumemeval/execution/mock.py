"""模拟执行器：不跑真实 agent，直接返回预设结果（验证编排逻辑用）。

设计要点：
- 继承 SessionExecutor（不依赖 adapters）
- 消费与 HarborBridge **同一个**注入契约（memory_mounts / agent_env /
  instruction_suffix / task_name / agent_memory_dir / session.env_extra）：
  否则「注入通道断了」这类 bug 只会在真跑时暴露，mock 测试全绿
- 把每个挂载的 host 侧文件清单写进 session_ctx["mock_injected_files"]
- 产出 mock_trial_dir → trial_dir，让 MemoryTransfer.collect 在 mock 下可测
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import SessionSpec
from .executor import SessionExecutor, SessionOutcome


class MockRunner(SessionExecutor):
    """模拟执行器。"""

    def __init__(self, mock_observations: list[str] | None = None):
        self.mock_observations = mock_observations or []

    async def run_session(
        self,
        session: SessionSpec,
        session_ctx: dict[str, Any],
    ) -> SessionOutcome:
        self._consume_memory_mounts(session_ctx)
        self._consume_agent_env(session_ctx, session)
        self._consume_runner_channels(session_ctx)
        obs = (
            self.mock_observations[session.id - 1]
            if session.id - 1 < len(self.mock_observations)
            else f"(mock obs for session {session.id})"
        )
        return SessionOutcome(session_id=session.id, success=True, observation=obs)

    @staticmethod
    def _consume_memory_mounts(session_ctx: dict[str, Any]) -> None:
        """列出 adapter 声明挂载的 host 侧文件（真实执行时这些会进容器）。"""
        injected: list[str] = []
        missing: list[str] = []
        for mount in session_ctx.get("memory_mounts") or []:
            host = Path(mount.host_path)
            if not host.exists():
                missing.append(str(host))
                continue
            if host.is_file():
                injected.append(f"{mount.container_path}")
                continue
            for path in sorted(host.rglob("*")):
                if path.is_file():
                    injected.append(f"{mount.container_path}/{path.relative_to(host)}")
        if missing:
            raise FileNotFoundError(
                "memory_mounts 指向不存在的 host 路径（Harbor bind mount 同样会失败）: " + ", ".join(missing)
            )
        session_ctx["mock_injected_files"] = injected

    @staticmethod
    def _consume_agent_env(session_ctx: dict[str, Any], session: SessionSpec) -> None:
        """记录 adapter / runner / session.env_extra 注入的 env。"""
        merged = dict(session_ctx.get("agent_env") or {})
        merged.update({str(k): str(v) for k, v in (session.env_extra or {}).items()})
        if merged:
            session_ctx.setdefault("mock_agent_env", {}).update(merged)

    @staticmethod
    def _consume_runner_channels(session_ctx: dict[str, Any]) -> None:
        """消费与 HarborBridge 相同的 runner 级通道，并模拟 trial_dir 产出。

        不消费这些键，runner 通道再断一次 mock 测试仍会全绿。产出 mock_trial_dir
        让 SessionRunner 的 MemoryTransfer.collect 在 mock 下也能走通。
        """
        session_ctx["mock_instruction_suffix"] = str(session_ctx.get("instruction_suffix") or "")
        session_ctx["mock_task_name"] = str(session_ctx.get("task_name") or "")
        session_ctx["mock_agent_memory_dir"] = session_ctx.get("agent_memory_dir")
        trial_dir = session_ctx.get("mock_trial_dir")
        if trial_dir is not None:
            session_ctx["trial_dir"] = Path(trial_dir)
