"""任务环境层：agentic 环境的可插拔扩展点。

agent-first 的环境缺口：MemoryArena 类任务里 agent 应在环境（webshop、旅行
规划器）中行动，而不是读摊平的文本。本模块定义 provider 契约——框架只负责把
环境**暴露给 agent**（endpoint / 使用提示 / env 变量），环境内行动的评分走各
benchmark 官方口径。各官方环境 server（webshop / travel …）是社区插件。

与 memory adapter 同范式：``register_task_environment`` 注册，执行层不感知
具体环境产品（lifecycle 经 session_ctx 消费，见 memory-instruction 契约）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cache

from .models import TaskEnvSpec

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


class WebshopTaskEnvironment(HttpTaskEnvironment):
    """MemoryArena 官方 webshop：HTTP env server + search[]/click[] 动作空间。

    协议对齐 vendors/MemoryArena/env/env_client.py：
    POST /env/initialize、/env/reset、/env/step、/env/get_observation、/env/close。
    框架只把 endpoint 和动作空间暴露给 agent；购买结果的官方打分仍走
    metrics.benchmarks.memoryarena_shopping（ASIN exact match）。
    """

    name = "webshop"

    def usage_hint(self, spec: TaskEnvSpec) -> str | None:
        endpoint = self.endpoint(spec)
        if not endpoint:
            return None
        custom = str(spec.config.get("usage_hint") or "")
        official = (
            f"任务环境是 MemoryArena webshop，服务 {endpoint}（env TASK_ENV_URL / WEBSHOP_ENV_URL）。\n"
            "协议（JSON POST）：\n"
            '- /env/initialize {task_id, env_name: "webshop", env_config}\n'
            "- /env/reset {task_id, seed}\n"
            "- /env/step {task_id, action}  → observation / reward / done / info\n"
            "- /env/get_observation {task_id}\n"
            "- /env/close {task_id}\n"
            "每回合只能发一个动作，格式必须是：\n"
            "- search[keywords]\n"
            "- click[product_id]  （点商品用 ASIN/ID，不要用商品名）\n"
            "- click[Back to Search] / click[< Prev] / click[Next >]\n"
            "- click[Buy Now]  （购买当前商品；info.last_purchased_asin 即本回合结果）\n"
            "- click[option_value]  （颜色/尺码等）\n"
            "不要把动作写在纯文本里假装买过；必须经 env server 走完 search→click→Buy Now。"
        )
        return f"{official}\n{custom}" if custom else official

    def env_vars(self, spec: TaskEnvSpec) -> dict[str, str]:
        endpoint = self.endpoint(spec)
        if not endpoint:
            return {}
        env_name = str(spec.config.get("env_name") or "webshop")
        return {
            "TASK_ENV_URL": endpoint,
            "WEBSHOP_ENV_URL": endpoint,
            "WEBSHOP_ENV_NAME": env_name,
        }


_PROVIDER_REGISTRY: dict[str, type[TaskEnvironmentProvider]] = {
    HttpTaskEnvironment.name: HttpTaskEnvironment,
    WebshopTaskEnvironment.name: WebshopTaskEnvironment,
}


def register_task_environment(cls: type[TaskEnvironmentProvider]) -> type[TaskEnvironmentProvider]:
    """注册环境 provider（扩展点）。"""
    if not getattr(cls, "name", None):
        raise ValueError(f"{cls.__name__} must set ClassVar name")
    _PROVIDER_REGISTRY[cls.name] = cls
    return cls


def task_environment_names() -> list[str]:
    return list(_PROVIDER_REGISTRY)


@cache
def _provider_instance(name: str) -> TaskEnvironmentProvider:
    cls = _PROVIDER_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown task environment: {name!r}. Supported: {task_environment_names()}")
    return cls()


def get_task_environment(name: str) -> TaskEnvironmentProvider:
    """按名取 provider 单例。"""
    return _provider_instance(name)
