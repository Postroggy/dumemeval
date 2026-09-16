"""任务环境层：agentic 环境的可插拔扩展点。

本模块定义 provider 契约和注册表，具体环境实现在数据集包中。
provider 暴露 endpoint / 使用提示 / env 变量，或提供受管准备与运行时。
环境内行动的评分走各 benchmark 官方口径，记忆仍由 memory adapter 管理。

与 memory adapter 同范式：``register_task_environment`` 注册，执行层不感知
具体环境产品（lifecycle 经 session_ctx 消费，见 memory-instruction 契约）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from .models import EvalTask, TaskEnvSpec
from .task_environments.base import EnvironmentPreparation, TaskEnvironmentRuntime

if TYPE_CHECKING:
    from .benchmarks.memoryarena.environment.providers import (
        WebshopTaskEnvironment,
    )

__all__ = [
    "HttpTaskEnvironment",
    "TaskEnvSpec",
    "TaskEnvironmentProvider",
    "WebshopTaskEnvironment",
    "get_task_environment",
    "register_task_environment",
    "task_environment_names",
]


class TaskEnvironmentProvider(ABC):
    """任务环境 provider 契约。子类设置 ``name`` 并实现三个方法。"""

    name: str = ""
    observed_control_keys: tuple[str, ...] = ()

    def prepare(self, spec: TaskEnvSpec, *, clone: bool = False) -> EnvironmentPreparation:
        """Inspect provisioned inputs; managed providers may opt into source preparation."""
        raise ValueError(f"Task environment {self.name!r} does not support managed preparation")

    def create_runtime(
        self, task: EvalTask, spec: TaskEnvSpec, output_dir: Path
    ) -> TaskEnvironmentRuntime | None:
        """Optionally own a task runtime; endpoint-only providers remain compatible."""
        return None

    @abstractmethod
    def endpoint(self, spec: TaskEnvSpec) -> str | None:
        """环境服务地址（None = 无独立 endpoint）。"""

    @abstractmethod
    def usage_hint(self, spec: TaskEnvSpec) -> str | None:
        """给 agent 的使用提示：环境能做什么、怎么交互。None = 不追加。"""

    @abstractmethod
    def env_vars(self, spec: TaskEnvSpec) -> dict[str, str]:
        """注入 agent 环境的变量（如 TASK_ENV_URL）。"""


class HttpTaskEnvironment(TaskEnvironmentProvider):
    """通用 HTTP 环境：把 base_url 暴露给 agent，供自建环境 server 直接接入。"""

    name = "http"

    def endpoint(self, spec: TaskEnvSpec) -> str | None:
        return spec.base_url

    def usage_hint(self, spec: TaskEnvSpec) -> str | None:
        endpoint = self.endpoint(spec)
        if not endpoint:
            return None
        custom = str(spec.config.get("usage_hint") or "")
        base = f"任务环境服务：{endpoint}（env TASK_ENV_URL）"
        return f"{base}\n{custom}" if custom else base

    def env_vars(self, spec: TaskEnvSpec) -> dict[str, str]:
        endpoint = self.endpoint(spec)
        return {"TASK_ENV_URL": endpoint} if endpoint else {}


_PROVIDER_REGISTRY: dict[str, type[TaskEnvironmentProvider]] = {
    HttpTaskEnvironment.name: HttpTaskEnvironment,
}


@cache
def _load_builtin_providers() -> None:
    from .benchmarks.memoryarena.environment.providers import PROVIDERS

    for cls in PROVIDERS:
        _PROVIDER_REGISTRY.setdefault(cls.name, cls)


def register_task_environment(cls: type[TaskEnvironmentProvider]) -> type[TaskEnvironmentProvider]:
    """注册环境 provider（扩展点）。"""
    if not getattr(cls, "name", None):
        raise ValueError(f"{cls.__name__} must set ClassVar name")
    _PROVIDER_REGISTRY[cls.name] = cls
    _provider_instance.cache_clear()
    return cls


def task_environment_names() -> list[str]:
    _load_builtin_providers()
    return list(_PROVIDER_REGISTRY)


@cache
def _provider_instance(name: str) -> TaskEnvironmentProvider:
    _load_builtin_providers()
    cls = _PROVIDER_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown task environment: {name!r}. Supported: {task_environment_names()}")
    return cls()


def get_task_environment(name: str) -> TaskEnvironmentProvider:
    """按名取 provider 单例。"""
    return _provider_instance(name)


def __getattr__(name: str) -> object:
    """Preserve the published provider imports without eager implementation imports."""
    if name in {"WebshopTaskEnvironment", "MemoryArenaTaskEnvironment"}:
        from .benchmarks.memoryarena.environment import providers

        return getattr(providers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
