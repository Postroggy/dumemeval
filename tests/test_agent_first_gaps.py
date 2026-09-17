"""测试：三个 agent-first 缺口的闭合。

1. memory_instruction：agent 被显式告知 memory 的存在与位置（可主动管理）
2. Utility 回填官方口径：task_success 反映任务结果而非完成率
3. 任务环境层：agentic 环境可插拔，agent 被告知环境交互方式
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dumemeval.environments import (
    get_task_environment,
    register_task_environment,
    task_environment_names,
)
from dumemeval.execution.executor import SessionExecutor
from dumemeval.execution.task_dir import TaskDirGenerator
from dumemeval.lifecycle.memory_transfer import MemoryTransfer
from dumemeval.lifecycle.runner import SessionRunner
from dumemeval.metrics.core.base import MetricInput
from dumemeval.metrics.dimensions.utility import UtilityEvaluator
from dumemeval.models import EvalTask, MemorySpec, SessionSpec, TaskEnvSpec, TaskExecution

# ── 公共构件 ────────────────────────────────────────────────────────────────


def _outcomes(successes: list[bool]) -> list[Any]:
    from dumemeval.execution.executor import SessionOutcome

    return [SessionOutcome(session_id=i + 1, success=s, observation="ok") for i, s in enumerate(successes)]


def _task(**kw: Any) -> EvalTask:
    defaults: dict[str, Any] = {
        "name": "t",
        "sessions": [
            SessionSpec(id=1, instruction="s1", memory_inject=True),
            SessionSpec(id=2, instruction="s2", memory_inject=True),
        ],
    }
    defaults.update(kw)
    return EvalTask(**defaults)


def _dir_adapter(tmp_path: Path) -> Any:
    from dumemeval.adapters.directory import DirectoryMemoryAdapter

    return DirectoryMemoryAdapter(MemorySpec(name="d", type="directory", path=str(tmp_path / "mem")))


def _run(adapter: Any, task: EvalTask, tmp_path: Path) -> list[dict[str, Any]]:
    """跑 SessionRunner，返回每个 session 的 session_ctx 快照。"""
    ctxs: list[dict[str, Any]] = []
    runner = SessionRunner(
        adapter=adapter,
        executor=_CapturingExecutor(ctxs),
        snapshot_dir=tmp_path / "snap",
        memory_transfer=MemoryTransfer(transfer_dir=tmp_path / "tr", mount_source=tmp_path / "mnt"),
    )
    import asyncio

    asyncio.run(runner.run(task))
    return ctxs


class _CapturingExecutor(SessionExecutor):
    """记录每个 session 的 session_ctx（契约消费侧）。"""

    def __init__(self, sink: list[dict[str, Any]]):
        self.sink = sink

    async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> Any:
        from dumemeval.execution.executor import SessionOutcome

        self.sink.append(dict(session_ctx))
        return SessionOutcome(session_id=session.id, success=True, observation="ok")


# ── Gap 1：memory_instruction ───────────────────────────────────────────────


class TestMemoryInstruction:
    def test_none_is_default_no_suffix(self, tmp_path: Path) -> None:
        ctxs = _run(_dir_adapter(tmp_path), _task(), tmp_path)
        assert all("instruction_suffix" not in c for c in ctxs)

    def test_location_tells_agent_where(self, tmp_path: Path) -> None:
        ctxs = _run(_dir_adapter(tmp_path), _task(memory_instruction="location"), tmp_path)
        for ctx in ctxs:
            assert "/app/memory" in ctx["instruction_suffix"]
            assert "主动写入" not in ctx["instruction_suffix"]

    def test_proactive_encourages_read_and_write(self, tmp_path: Path) -> None:
        ctxs = _run(_dir_adapter(tmp_path), _task(memory_instruction="proactive"), tmp_path)
        for ctx in ctxs:
            assert "/app/memory" in ctx["instruction_suffix"]
            assert "写入" in ctx["instruction_suffix"]
            assert "回忆" in ctx["instruction_suffix"]

    def test_no_hint_means_no_suffix_even_in_proactive(self, tmp_path: Path) -> None:
        """provider / adapter 无 hint 时不能编造内容（suffix 为空）。"""
        from dumemeval.environments import TaskEnvironmentProvider, register_task_environment

        class _Silent(TaskEnvironmentProvider):
            name = "silent-env"

            def endpoint(self, spec: Any) -> str | None:
                return None

            def usage_hint(self, spec: Any) -> str | None:
                return None

            def env_vars(self, spec: Any) -> dict[str, str]:
                return {}

        register_task_environment(_Silent)
        task = _task(memory_instruction="proactive")
        task.task_environment = {"type": "silent-env"}

        from dumemeval.adapters.directory import DirectoryMemoryAdapter

        class _NoHintAdapter(DirectoryMemoryAdapter):
            def memory_usage_hint(self) -> str | None:
                return None

        adapter = _NoHintAdapter(MemorySpec(name="d2", type="directory", path=str(tmp_path / "mem2")))
        ctxs = _run(adapter, task, tmp_path)
        assert all(not ctx.get("instruction_suffix") for ctx in ctxs)

    def test_task_dir_writes_suffix_into_instruction_md(self, tmp_path: Path) -> None:
        gen = TaskDirGenerator(tasks_root=tmp_path)
        session = SessionSpec(id=1, instruction="原任务指令")
        task_dir = gen.generate(session, instruction_suffix="\n\n[持久记忆] 位于 /app/memory，可读写。")
        md = (task_dir / "instruction.md").read_text()
        assert md.startswith("原任务指令")
        assert "/app/memory" in md


# ── Gap 2：Utility 回填官方口径 ─────────────────────────────────────────────


class TestUtilityOfficialBackfill:
    def test_official_score_overrides_completion(self) -> None:
        """3/3 session 完成（完成率 1.0）但官方分 0.0 → task_success=False。"""
        bundle = UtilityEvaluator().calculate(
            MetricInput(
                execution=TaskExecution(
                    task_id="t",
                    task_name="t",
                    memory_backend="m",
                    sessions=_outcomes([True, True, True]),
                ),
                extra={"official_task_score": 0.0},
            )
        )
        assert bundle.values["task_success"] == 0.0
        assert bundle.values["success_rate"] == 1.0
        assert bundle.details[-1]["source"] == "benchmark_official"

    def test_official_score_pass_threshold(self) -> None:
        bundle = UtilityEvaluator().calculate(
            MetricInput(
                execution=TaskExecution(
                    task_id="t", task_name="t", memory_backend="m", sessions=_outcomes([True])
                ),
                extra={"official_task_score": 0.83},
            )
        )
        assert bundle.values["task_success"] == 1.0
        assert bundle.details[-1]["score"] == pytest.approx(0.83)

    def test_no_official_falls_back_to_completion(self) -> None:
        """无官方口径（自定义任务）保持完成率语义。"""
        bundle = UtilityEvaluator().calculate(
            MetricInput(
                execution=TaskExecution(
                    task_id="t",
                    task_name="t",
                    memory_backend="m",
                    sessions=_outcomes([True, False]),
                )
            )
        )
        assert bundle.values["task_success"] == 0.0
        assert bundle.values["success_rate"] == 0.5
        assert not any(d.get("source") == "benchmark_official" for d in bundle.details)

    def test_metricinput_extra_channel(self) -> None:
        """pipeline 经 MetricInput.extra 传入官方分（不增加计算器间耦合）。"""
        bundle = UtilityEvaluator().calculate(
            MetricInput(
                execution=TaskExecution(task_id="t", task_name="t", memory_backend="m", sessions=[]),
                extra={"official_task_score": 0.0},
            )
        )
        assert bundle.values["task_success"] == 0.0


# ── Gap 3：任务环境层 ───────────────────────────────────────────────────────


class TestEnvironmentRegistry:
    def test_register_and_get(self) -> None:
        from dumemeval.environments import TaskEnvironmentProvider

        @register_task_environment
        class _Toy(TaskEnvironmentProvider):
            name = "toy-env"

            def endpoint(self, spec: TaskEnvSpec) -> str:
                return spec.base_url or ""

            def usage_hint(self, spec: TaskEnvSpec) -> str:
                return "用 search[x] 搜索。"

            def env_vars(self, spec: TaskEnvSpec) -> dict[str, str]:
                return {"TOY_URL": self.endpoint(spec)}

        try:
            provider = get_task_environment("toy-env")
            spec = TaskEnvSpec(type="toy-env", base_url="http://env:9000")
            assert provider.endpoint(spec) == "http://env:9000"
            hint = provider.usage_hint(spec)
            assert hint is not None and "search[x]" in hint
            assert "toy-env" in task_environment_names()
        finally:
            from dumemeval import environments as env_mod

            env_mod._PROVIDER_REGISTRY.pop("toy-env", None)

    def test_unknown_type_raises_with_available(self) -> None:
        with pytest.raises(ValueError, match="http"):
            get_task_environment("nope")

    def test_webshop_provider_exposes_official_actions(self) -> None:
        provider = get_task_environment("webshop")
        spec = TaskEnvSpec(type="webshop", base_url="http://127.0.0.1:8005")
        hint = provider.usage_hint(spec) or ""
        assert "search[" in hint and "click[Buy Now]" in hint
        assert "/env/step" in hint
        env = provider.env_vars(spec)
        assert env["WEBSHOP_ENV_URL"] == "http://127.0.0.1:8005"
        assert env["TASK_ENV_URL"] == env["WEBSHOP_ENV_URL"]

    def test_builtin_http_provider(self) -> None:
        spec = TaskEnvSpec(type="http", base_url="http://env:9000")
        provider = get_task_environment("http")
        assert provider.endpoint(spec) == "http://env:9000"
        assert "TASK_ENV_URL" in provider.env_vars(spec)


class TestEnvironmentInRunner:
    def test_runner_injects_env_vars_and_hint(self, tmp_path: Path) -> None:
        task = _task(
            memory_instruction="proactive",
            task_environment={
                "type": "http",
                "base_url": "http://env:9000",
                "config": {"usage_hint": "在环境中用 GET /search?q= 搜索商品。"},
            },
        )
        ctxs = _run(_dir_adapter(tmp_path), task, tmp_path)
        for ctx in ctxs:
            env = ctx["agent_env"]
            assert env.get("TASK_ENV_URL") == "http://env:9000"
            suffix = ctx["instruction_suffix"]
            assert "/app/memory" in suffix  # memory 部分
            assert "GET /search" in suffix  # 环境部分
