"""Harbor 执行器：在 Harbor 隔离环境里跑 agent。

设计要点：
- 只做"SessionSpec → Harbor trial → SessionOutcome"（执行职责）
- memory 生命周期（注入/收集）由 SessionRunner + MemoryTransfer 编排
- 使用 trial_config.build_trial_config（纯函数）+ HarborConfig（pydantic）
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from ..models import SessionSpec
from .executor import SessionExecutor, SessionOutcome
from .trial_config import HarborConfig, MountConfig, build_trial_config

logger = logging.getLogger(__name__)

# ATIF trajectory.json 相对 trial_dir 的路径（官方 agent 落盘位置，
# 见 harbor.agents.installed.claude_code.populate_context_post_run）
_TRAJECTORY_RELATIVE_PATH = "agent/trajectory.json"


def sanitize_task_name(name: str) -> str:
    """task 名 → 文件系统安全段（并行时作 trial/task 目录的隔离前缀）。"""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._-")
    return safe or "task"


class HarborBridge(SessionExecutor):
    """Harbor 执行器。"""

    def __init__(
        self,
        config: HarborConfig | None = None,
        task_dir_generator: Any | None = None,
    ):
        self.config = config or HarborConfig()
        self.task_dir_generator = task_dir_generator

    async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
        from ..artifacts.redaction import Redactor

        redactor = Redactor(
            {
                **os.environ,
                **self.config.environment.env,
                **session_ctx.get("agent_env", {}),
                **session.env_extra,
            }
        )
        try:
            outcome = await self._run_session(session, session_ctx)
            return SessionOutcome.model_validate_json(redactor.text(outcome.model_dump_json()))
        finally:
            task_name = sanitize_task_name(str(session_ctx.get("task_name") or "task"))
            trial_dir = Path(self.config.trials_dir) / f"dumemeval_{task_name}__session_{session.id}"
            redactor.tree(trial_dir)

    async def _run_session(
        self,
        session: SessionSpec,
        session_ctx: dict[str, Any],
    ) -> SessionOutcome:
        """在 Harbor 隔离环境里跑一个 session。

        流程：
        1. 生成 Harbor task 目录（instruction.md + tests/）
        2. 从 session_ctx 读 memory 注入目标（SessionRunner 已注入）
        3. 创建并运行 Harbor trial
        4. 解析 TrialResult → SessionOutcome（reward/success + agent 输出 + token 用量）
        """
        try:
            from harbor.trial.trial import Trial
        except ImportError as e:
            raise ImportError(
                "HarborBridge requires Harbor installed. "
                "Install with: pip install harbor (or add vendors/harbor to PYTHONPATH)"
            ) from e

        if self.task_dir_generator is None:
            raise RuntimeError("HarborBridge requires task_dir_generator (TaskDirGenerator)")
        # 跨 task 并行时用 task_name 隔离 task_dir 与 trial_name（防目录冲突）
        task_name = sanitize_task_name(str(session_ctx.get("task_name") or "task"))
        task_dir = self.task_dir_generator.generate(
            session, task_name=task_name, instruction_suffix=str(session_ctx.get("instruction_suffix") or "")
        )

        # 从 session_ctx 读 memory 注入目标（SessionRunner 的 MemoryTransfer 已注入）
        memory_dir = session_ctx.get("agent_memory_dir")

        # adapter 声明的挂载（统一 memory_mounts 契约；执行层不认识具体产品）
        extra_mounts = [
            MountConfig(
                type="bind",
                source=str(Path(mount.host_path).resolve()),
                target=mount.container_path,
                read_only=mount.read_only,
            )
            for mount in [
                *(session_ctx.get("memory_mounts") or []),
                *(session_ctx.get("runtime_mounts") or []),
            ]
        ]

        agent_env = dict(session_ctx.get("agent_env") or {})
        agent_env.update({str(k): str(v) for k, v in (session.env_extra or {}).items()})

        trial_config = build_trial_config(
            self.config,
            session,
            task_dir,
            memory_dir,
            extra_mounts=extra_mounts,
            task_name=task_name,
            # adapter / runner 注入的容器级 env（DUMEMEVAL_MEMORY_DIR / HERMES_* 等）
            # + session.env_extra（per-session 覆盖）
            agent_env=agent_env,
        )
        from harbor.models.trial.config import TrialConfig

        trial = await Trial.create(config=TrialConfig(**trial_config))
        result = None
        try:
            result = await trial.run()
        except Exception as e:
            # Harbor 0.22 在 verifier schema 校验失败时抛异常，但 agent 可能已经
            # 跑完并落盘 trajectory——host 侧 metrics 只需要这段输出。
            logger.warning("Harbor trial.run() 抛异常，尝试从 trial_dir 回收 agent 输出: %s", e)
            trial_dir = getattr(getattr(trial, "paths", None), "trial_dir", None)
            outcome = SessionOutcome(session_id=session.id, error=str(e))
            observation = self._extract_agent_output(trial_dir)
            if observation:
                outcome.observation = observation
            if trial_dir is not None:
                session_ctx["trial_dir"] = trial_dir
            outcome.artifacts = self._collect_artifacts(session, trial_dir)
            return outcome

        trial_dir = getattr(getattr(trial, "paths", None), "trial_dir", None)
        outcome = self._parse_trial_result(session, result, trial_dir)

        # 把 trial 目录写进 session_ctx（供 SessionRunner 收集 memory）
        if trial_dir is not None and getattr(result, "exception_info", None) is None:
            session_ctx["trial_dir"] = trial_dir

        # 收集 session 声明的 artifacts（B-3：产物收集）
        outcome.artifacts = self._collect_artifacts(session, trial_dir)

        return outcome

    def _collect_artifacts(self, session: SessionSpec, trial_dir: Path | None) -> dict[str, Path]:
        """按 session.artifacts 收集产物文件。

        从 trial 目录的 agent 输出区复制声明的文件到 outcome.artifacts。
        未声明 artifacts 或目录不存在时返回空 dict。
        """
        artifacts: dict[str, Path] = {}
        if trial_dir is None:
            return artifacts
        agent_dir = trial_dir / "agent"
        trajectory = agent_dir / "trajectory.json"
        if trajectory.is_file():
            artifacts["agent_trajectory"] = trajectory
        if not agent_dir.exists():
            return artifacts
        for name in session.artifacts:
            candidates = list(agent_dir.rglob(name))
            if candidates:
                artifacts[name] = candidates[0]
            else:
                logger.warning("artifact 未找到: %s（session %d）", name, session.id)
        return artifacts

    def _parse_trial_result(
        self, session: SessionSpec, trial_result: Any, trial_dir: Path | None
    ) -> SessionOutcome:
        """解析 Harbor TrialResult → SessionOutcome。

        success 语义：**「跑完且产出了可判分的输出」**，不是「任务做对」——
        任务对错由 host 的 `metrics/` 按官方口径判。此前 success 从 Harbor
        reward（>=0.5）推导，而默认容器 verifier 是 no-op（reward 恒 0）或
        空 ground_truth 下恒 1.0，两种都会让 success 成为假信号。

        判定：无异常 **且** 采集到 agent 输出；用户显式配置容器 verifier 且
        Harbor 返回 is_success 时以其为准。
        """
        outcome = SessionOutcome(session_id=session.id)
        if trial_result is None:
            outcome.error = "trial result is None"
            return outcome

        verifier_result = getattr(trial_result, "verifier_result", None)
        if verifier_result is not None:
            rewards = getattr(verifier_result, "rewards", None)
            if isinstance(rewards, dict):
                outcome.reward = float(rewards.get("total", 0.0))
            elif isinstance(rewards, int | float):
                outcome.reward = float(rewards)

        exc = getattr(trial_result, "exception_info", None)
        if exc is not None:
            outcome.error = f"{getattr(exc, 'exception_type', '')}: {getattr(exc, 'exception_message', '')}"

        n_input, _n_cache, n_output, _cost = self._token_cost_totals(trial_result)
        if n_input is not None:
            outcome.tokens_in = n_input
        if n_output is not None:
            outcome.tokens_out = n_output

        observation = self._extract_agent_output(trial_dir)
        if observation:
            outcome.observation = observation
        elif exc is None:
            logger.warning(
                "session %d: 未能从 %s 提取 agent 输出文本，observation 为空"
                "（依赖 agent 输出的 benchmark 指标会算出 0 分）",
                session.id,
                trial_dir / _TRAJECTORY_RELATIVE_PATH if trial_dir else "<no trial_dir>",
            )

        is_success = getattr(verifier_result, "is_success", None) if verifier_result else None
        if is_success is not None:
            outcome.success = exc is None and bool(is_success)
        else:
            outcome.success = exc is None and bool(outcome.observation)

        return outcome

    @staticmethod
    def _token_cost_totals(
        trial_result: Any,
    ) -> tuple[int | None, int | None, int | None, float | None]:
        """调用官方 TrialResult.compute_token_cost_totals()（若存在）。"""
        compute = getattr(trial_result, "compute_token_cost_totals", None)
        if compute is None:
            return None, None, None, None
        try:
            result = compute()
        except Exception:
            logger.exception("compute_token_cost_totals() 调用失败")
            return None, None, None, None
        if not isinstance(result, tuple) or len(result) != 4:
            return None, None, None, None
        return result

    @staticmethod
    def _extract_agent_output(trial_dir: Path | None) -> str:
        """从 ``trial_dir/agent/trajectory.json``（ATIF Trajectory）取 agent
        最后一条文本消息，作为该 session 的最终输出。

        找不到文件、解析失败、或没有任何 agent 文本 step 时返回空字符串
        （调用方按"未采集到输出"处理，不在这里静默伪造数据）。
        """
        if trial_dir is None:
            return ""
        traj_path = Path(trial_dir) / _TRAJECTORY_RELATIVE_PATH
        if not traj_path.exists():
            return ""
        try:
            from harbor.models.trajectories.trajectory import Trajectory

            trajectory = Trajectory.model_validate_json(traj_path.read_text())
        except Exception:
            logger.exception("解析 trajectory.json 失败: %s", traj_path)
            return ""

        for step in reversed(trajectory.steps):
            if step.source != "agent":
                continue
            message = step.message
            if isinstance(message, str) and message.strip():
                return message
            if isinstance(message, list):
                # ATIF-v1.6+ 多模态：拼接文本类 ContentPart，忽略图片等
                text_parts = [
                    getattr(part, "text", "")
                    for part in message
                    if getattr(part, "type", "") == "text" and getattr(part, "text", "")
                ]
                if text_parts:
                    return "\n".join(text_parts)
        return ""
