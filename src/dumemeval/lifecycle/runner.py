"""SessionRunner：multi-session 评测编排器。

设计要点：
- 编排 executor（执行）+ adapter（memory）+ MemoryTransfer（传递）+ hooks（事件）
- 感知协议（EvalProtocol）：协议决定"每个 session 是否注入/收集 memory"
- 指标计算走 MetricsAggregator（Utility + Efficiency）；Quality / benchmark 由 CLI 汇入同一入口
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..adapters.base import BaseMemoryAdapter
from ..core.instructions import instruction_digest
from ..core.protocol import EvalProtocol, MemorySessionTransferProtocol
from ..execution.executor import SessionExecutor, SessionOutcome
from ..models import EvalTask, TaskExecution
from .hooks import LifecycleEvent, LifecycleHooks
from .memory_transfer import MemoryTransfer


class SessionRunner:
    """multi-session 评测执行器。"""

    def __init__(
        self,
        adapter: BaseMemoryAdapter,
        executor: SessionExecutor,
        protocol: EvalProtocol | None = None,
        memory_transfer: MemoryTransfer | None = None,
        snapshot_dir: Path | None = None,
        hooks: LifecycleHooks | None = None,
    ):
        self.adapter = adapter
        self.executor = executor
        self.protocol = protocol or MemorySessionTransferProtocol()
        self.memory_transfer = memory_transfer or MemoryTransfer()
        self.snapshot_dir = (
            Path(snapshot_dir) if snapshot_dir else Path("results") / "snapshots" / adapter.name
        )
        self.hooks = hooks or LifecycleHooks()

    async def run(self, task: EvalTask) -> TaskExecution:
        """执行整个 multi-session 任务。"""
        session_ctx: dict[str, Any] = {
            "agent_env": {},
            "task_name": task.name,
            "memory_transfer_dir": str(self.memory_transfer.transfer_dir),
        }

        memory_enabled = self.protocol.should_inject_memory(True) and self.adapter.spec.type != "none"
        self.adapter.setup(task)
        # benchmark 评测：先把历史对话灌入被测 memory（如 Hermes L0 seed）
        if memory_enabled and task.data.get("initial_memory") and not self.adapter.supports_initial_memory:
            raise ValueError("This memory adapter cannot seed the task's required initial memory")
        if memory_enabled and task.data.get("host_memory_history") and not self.adapter.supports_host_history:
            raise ValueError("This memory adapter cannot append the task's required environment history")
        if memory_enabled:
            self.adapter.seed_history(task)
        session_ctx["memory_enabled"] = memory_enabled
        await self.hooks.emit(LifecycleEvent.EVAL_START, task.sessions[0], session_ctx)

        # memory_instruction / task_environment 的 instruction 后缀（全 task 一致）
        instruction_suffix = self._compose_instruction_suffix(task, session_ctx)
        environment_suffix = self._compose_instruction_suffix(task, session_ctx, include_memory=False)
        environment_vars = dict(session_ctx.get("agent_env", {}))

        session_outcomes: list[SessionOutcome] = []

        for session in task.sessions:
            # Bindings belong to one session; their backing memory survives in the adapter.
            session_ctx["agent_env"] = dict(environment_vars)
            session_ctx.pop("memory_mounts", None)
            session_ctx.pop("agent_memory_dir", None)
            # Tool access is an experiment control, independent of memory injection.
            if environment_suffix:
                session_ctx["instruction_suffix"] = environment_suffix
            else:
                session_ctx.pop("instruction_suffix", None)
            await self.hooks.emit(LifecycleEvent.SESSION_START, session, session_ctx)

            if self.protocol.should_inject_memory(session.memory_inject):
                memory_dir = self.memory_transfer.inject(session_ctx)
                if memory_dir:
                    session_ctx["agent_memory_dir"] = memory_dir

            if self.protocol.should_adapter_inject(session.memory_inject):
                self.adapter.inject(session, session_ctx)
                # memory_instruction：告知 agent 持久记忆的存在（agent-first 契约）
                if instruction_suffix and session.memory_inject:
                    session_ctx["instruction_suffix"] = instruction_suffix
            await self.hooks.emit(LifecycleEvent.MEMORY_INJECTED, session, session_ctx)

            try:
                outcome = await self.executor.run_session(session, session_ctx)
            except Exception as e:
                outcome = SessionOutcome(session_id=session.id, success=False, error=str(e))
                await self.hooks.emit(LifecycleEvent.ERROR, session, session_ctx)
            outcome.query = session.query
            session_outcomes.append(outcome)
            if outcome.instruction_sha256 is None:
                outcome.instruction_sha256 = instruction_digest(
                    session.instruction, str(session_ctx.get("instruction_suffix") or "")
                )

            trial_dir = session_ctx.pop("trial_dir", None)
            if trial_dir is not None:
                outcome.trial_dir = str(trial_dir)
            if self.protocol.should_adapter_inject(session.memory_inject):
                self.adapter.observe_execution(session, outcome)
                # A completed environment submission remains part of the official
                # history even when another tool call makes the session fail.
                if outcome.memory_entry:
                    self.adapter.append_history(session, outcome.memory_entry)
            if self.protocol.should_snapshot(session.memory_inject):
                self.adapter.snapshot(session, self.snapshot_dir)
            if trial_dir is not None and self.protocol.should_collect_memory(session.memory_inject):
                self.memory_transfer.collect(trial_dir, session)
                await self.hooks.emit(LifecycleEvent.MEMORY_COLLECTED, session, session_ctx)

            await self.hooks.emit(LifecycleEvent.SESSION_END, session, session_ctx)

        await self.hooks.emit(LifecycleEvent.EVAL_END, task.sessions[-1], session_ctx)

        artifacts = {}
        for outcome in session_outcomes:
            artifacts.update(outcome.artifacts)
        return TaskExecution(
            task_id=task.name,
            task_name=task.name,
            memory_backend=self.adapter.name,
            sessions=session_outcomes,
            memory_ops=self.adapter.all_ops(),
            artifacts=artifacts,
            status=(
                "completed"
                if all(outcome.success for outcome in session_outcomes)
                else "partial"
                if any(outcome.success for outcome in session_outcomes)
                else "failed"
            ),
        )

    # ── instruction 后缀组装（memory_instruction + task_environment）─────────

    def _compose_instruction_suffix(
        self, task: EvalTask, session_ctx: dict[str, Any], *, include_memory: bool = True
    ) -> str:
        """按模式把「memory 在哪、环境怎么用」组合成 instruction 后缀。

        - memory：none=不告知；location=只告知位置；proactive=位置 + 主动读写要求
        - 环境：provider 的 usage_hint（环境可交互性必须显式告知——同 memory 的教训），
          env 变量并入 agent_env（同 dict 跨 session 存续，与 adapter 注入一致）
        环境提示独立于 memory；test_only 保留完全相同的工具使用提示。
        """
        parts: list[str] = []

        mode = getattr(task, "memory_instruction", "none") or "none"
        if include_memory and mode != "none":
            hint = getattr(self.adapter, "memory_usage_hint", lambda: None)()
            if hint:
                if mode == "location":
                    parts.append(f"[持久记忆] {hint}。需要时可用工具读取。")
                else:  # proactive
                    parts.append(
                        f"[持久记忆] {hint}。\n"
                        "- 回答前：先用工具回忆其中与任务相关的历史信息。\n"
                        "- 学到值得跨会话保留的信息：主动写入，不要依赖单次对话。"
                    )

        env_spec = getattr(task, "task_environment", None) or {}
        if env_spec.get("type"):
            from ..environments import TaskEnvSpec, get_task_environment

            provider = get_task_environment(str(env_spec["type"]))
            spec_obj = TaskEnvSpec(
                type=str(env_spec["type"]),
                base_url=env_spec.get("base_url"),
                config=dict(env_spec.get("config") or {}),
            )
            env_vars = provider.env_vars(spec_obj)
            if env_vars:
                session_ctx.setdefault("agent_env", {}).update(env_vars)
            hint = provider.usage_hint(spec_obj)
            if hint:
                parts.append(f"[任务环境] {hint}")

        return "\n".join(parts)
