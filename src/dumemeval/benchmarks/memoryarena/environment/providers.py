"""MemoryArena environment providers.

Source: https://github.com/ZexueHe/MemoryArena
"""

from pathlib import Path

from dumemeval.environments import (
    HttpTaskEnvironment,
    TaskEnvironmentProvider,
    register_task_environment,
)
from dumemeval.models import EvalTask, TaskEnvSpec
from dumemeval.task_environments.base import EnvironmentPreparation, TaskEnvironmentRuntime


@register_task_environment
class WebshopTaskEnvironment(HttpTaskEnvironment):
    """MemoryArena 官方 webshop：HTTP env server + search[]/click[] 动作空间。

    协议对齐 vendors/MemoryArena/env/env_client.py：
    POST /env/initialize、/env/reset、/env/step、/env/get_observation、/env/close。
    框架只把 endpoint 和动作空间暴露给 agent；购买结果的官方打分仍走
    benchmarks.memoryarena.metrics.shopping（ASIN exact match）。
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


@register_task_environment
class MemoryArenaTaskEnvironment(TaskEnvironmentProvider):
    """Managed official MemoryArena tools, registered through the existing boundary.

    Source: https://github.com/ZexueHe/MemoryArena
    """

    name = "memoryarena"
    observed_control_keys = ("observed_environment", "observed_agent")

    def prepare(self, spec: TaskEnvSpec, *, clone: bool = False) -> EnvironmentPreparation:
        from .config import ArenaRuntimeConfig
        from .prepare import inspect_environment

        return inspect_environment(ArenaRuntimeConfig.model_validate(spec.config), clone=clone)

    def endpoint(self, spec: TaskEnvSpec) -> str | None:
        return None

    def usage_hint(self, spec: TaskEnvSpec) -> str | None:
        return None

    def env_vars(self, spec: TaskEnvSpec) -> dict[str, str]:
        return {}

    def create_runtime(self, task: EvalTask, spec: TaskEnvSpec, output_dir: Path) -> TaskEnvironmentRuntime:
        from .config import ArenaRuntimeConfig
        from .runtime import MemoryArenaRuntime

        return MemoryArenaRuntime(task, ArenaRuntimeConfig.model_validate(spec.config), output_dir)
