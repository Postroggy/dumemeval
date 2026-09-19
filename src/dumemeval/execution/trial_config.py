"""Harbor TrialConfig 构建（纯函数，无 Harbor 运行时依赖）。

设计要点：
- 从 HarborBridge 抽出：职责单一（config 构建）
- 不 import Harbor（仅类型注释用 TYPE_CHECKING）——保持可测试
- harbor_config 用 pydantic HarborConfig 约束（非裸 dict）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..models import SessionSpec

# ── Harbor 配置模型（替代裸 dict）───────────────────────────────────────────


class MountConfig(BaseModel):
    """目录挂载配置（映射到 Harbor 的 volume 配置）。"""

    type: Literal["bind"] = Field(default="bind")
    source: str = Field(description="host 路径")
    target: str = Field(description="容器内路径")
    read_only: bool = False


class HarborEnvironmentConfig(BaseModel):
    """Harbor 环境配置。"""

    type: Literal["docker"] = Field(default="docker")
    delete: bool = True
    force_build: bool = Field(default=True)
    docker_image: str | None = Field(
        default=None,
        description="预构建镜像（如含 hermes 的 dumeval-hermes:latest），设置后跳过 Dockerfile 构建",
    )
    env: dict[str, str] = Field(default_factory=dict)
    mounts: list[MountConfig] = Field(default_factory=list)


class HarborAgentConfig(BaseModel):
    """Harbor agent 配置。"""

    name: str = Field(default="claude-code")
    version: str | None = None
    model: str | None = None
    setup_timeout_sec: float = Field(default=900.0, ge=0)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    skills_dir: str | None = None


class HarborConfig(BaseModel):
    """Harbor 执行层完整配置（替代裸 dict harbor_config）。"""

    trials_dir: str = Field(default="trials")
    agent: HarborAgentConfig = Field(default_factory=HarborAgentConfig)
    environment: HarborEnvironmentConfig = Field(default_factory=HarborEnvironmentConfig)


# ── TrialConfig 构建 ────────────────────────────────────────────────────────


def build_trial_config(
    config: HarborConfig,
    session: SessionSpec,
    task_dir: Path,
    memory_dir: str | None = None,
    extra_mounts: list[MountConfig] | None = None,
    task_name: str = "task",
    agent_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构建 Harbor TrialConfig（dict 形式，由 HarborBridge 实例化）。

    Args:
        config: Harbor 配置（pydantic）
        session: session 定义
        task_dir: 生成的 task 目录
        memory_dir: 容器内 memory 目录（注入 claude auto-memory），None 不注入
        extra_mounts: 额外 bind mount（如 hermes_builtin 的 memories 目录挂载）
        task_name: task 标识（跨 task 并行时隔离 trial_name，防目录冲突）
        agent_env: adapter / runner 注入的容器级环境变量（session_ctx["agent_env"]；
            与 yaml execution.environment.env 合并，后者优先级低）。session.env_extra
            在执行器侧并入 agent_env，本函数不单独处理。

    Returns:
        dict: TrialConfig 的字段（可直接 TrialConfig(**result)）
    """
    agent_kwargs: dict[str, Any] = {}
    if config.agent.version:
        agent_kwargs["version"] = config.agent.version
    if memory_dir:
        agent_kwargs["memory_dir"] = memory_dir
    if config.agent.temperature is not None:
        agent_kwargs["temperature"] = config.agent.temperature
    if config.agent.max_tokens is not None:
        agent_kwargs["max_tokens"] = config.agent.max_tokens
    if config.agent.skills_dir:
        agent_kwargs["skills_dir"] = config.agent.skills_dir

    # 环境变量合并：yaml 配置（认证/网关等）为底，adapter/runner 注入的 agent_env 覆盖
    env = dict(config.environment.env)
    if agent_env:
        env.update(agent_env)

    cfg: dict[str, Any] = {
        "trial_name": f"dumemeval_{task_name}__session_{session.id}",
        "trials_dir": config.trials_dir,
        "task": {
            "path": str(task_dir),
            **(
                {"environment": {"docker_image": config.environment.docker_image}}
                if config.environment.docker_image
                else {}
            ),
        },
        "agent": {
            "name": config.agent.name,
            "model_name": config.agent.model,
            "override_setup_timeout_sec": config.agent.setup_timeout_sec,
            **({"kwargs": agent_kwargs} if agent_kwargs else {}),
        },
        "environment": {
            "type": config.environment.type,
            "delete": config.environment.delete,
            "force_build": config.environment.force_build,
        },
        "verifier": {"override_timeout_sec": 600.0},
    }
    mounts = list(config.environment.mounts)
    if extra_mounts:
        mounts.extend(extra_mounts)
    if mounts:
        cfg["environment"]["mounts"] = [
            {**m.model_dump(exclude={"read_only"}), **({"read_only": True} if m.read_only else {})}
            for m in mounts
        ]
    if env:
        # Harbor 侧经 EnvironmentConfig.env → docker compose environment 注入容器
        cfg["environment"]["env"] = env
    return cfg
