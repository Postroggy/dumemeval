"""测试：adapter 注入契约（memory 必须真的进入 agent 环境）。

背景：`DirectoryMemoryAdapter.inject` 曾依赖 `session_ctx["agent_memory_target"]`，
但没有任何执行器设置该键——注入永远静默跳过，且 mock 与真实「一致地错」，
测试全绿。本文件锁住契约：inject 必须写下游会消费的通道。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dumemeval.adapters.registry import adapter_names, create_adapter
from dumemeval.models import EvalTask, MemorySpec, SessionSpec

# 需要外部服务的 adapter：setup 会发 HTTP，契约测试跳过（各自有专门测试）
_NEEDS_SERVICE = {"http", "everos"}
# 语义上「无注入」的 adapter：none 的本意就是不写任何通道（docs/architecture/run-artifacts.md）
_NOOP = {"none"}


def _task() -> EvalTask:
    return EvalTask(
        name="contract-task",
        sessions=[
            SessionSpec(id=1, instruction="记住偏好", memory_inject=True),
            SessionSpec(id=2, instruction="应用偏好", memory_inject=True),
        ],
    )


def _local_adapter_types() -> list[str]:
    return [name for name in adapter_names() if name not in _NEEDS_SERVICE | _NOOP]


# hermes_builtin 必须显式配 model（框架不预设厂商模型）
def _spec_for(adapter_type: str, tmp_path: Path) -> MemorySpec:
    config: dict[str, Any] = (
        {"model": "test-model", "base_url": "https://gw.example/v1", "api_key": "k"}
        if adapter_type == "hermes_builtin"
        else {}
    )
    return MemorySpec(
        name=f"{adapter_type}-contract", type=adapter_type, path=str(tmp_path / "mem"), config=config
    )


@pytest.mark.parametrize("adapter_type", _local_adapter_types())
def test_inject_declares_a_channel(adapter_type: str, tmp_path: Path) -> None:
    """每个本地 adapter 的 inject 必须写至少一条下游可消费的通道。

    通道 = memory_mounts（bind 挂载）或 agent_env（环境变量）。
    两者都空 = 注入是 no-op，memory 到不了 agent。
    """
    adapter = create_adapter(_spec_for(adapter_type, tmp_path))
    task = _task()
    adapter.setup(task)

    session_ctx: dict[str, Any] = {"agent_env": {}}
    adapter.inject(task.sessions[0], session_ctx)

    mounts = session_ctx.get("memory_mounts") or []
    env = session_ctx.get("agent_env") or {}
    assert mounts or env, (
        f"{adapter_type}.inject 没有写任何注入通道（memory_mounts / agent_env 均空）——"
        "memory 到不了 agent，这是静默失败"
    )


@pytest.mark.parametrize("adapter_type", _local_adapter_types())
def test_declared_mount_host_paths_exist(adapter_type: str, tmp_path: Path) -> None:
    """声明的 host 路径必须真实存在，否则挂载会失败或挂空目录。"""
    adapter = create_adapter(_spec_for(adapter_type, tmp_path))
    task = _task()
    adapter.setup(task)
    session_ctx: dict[str, Any] = {"agent_env": {}}
    adapter.inject(task.sessions[0], session_ctx)

    for mount in session_ctx.get("memory_mounts") or []:
        assert Path(mount.host_path).exists(), f"{adapter_type} 声明了不存在的 host 路径 {mount.host_path}"
        assert mount.container_path.startswith("/"), "container_path 必须是绝对路径"


class TestDirectoryAdapterInjection:
    """directory 是默认类型，也是 quickstart 用的类型——单独锁死。"""

    def test_declares_container_mount(self, tmp_path: Path) -> None:
        from dumemeval.adapters.directory import CONTAINER_MEMORY_DIR, DirectoryMemoryAdapter

        adapter = DirectoryMemoryAdapter(MemorySpec(name="d", type="directory", path=str(tmp_path / "mem")))
        task = _task()
        adapter.setup(task)
        (adapter.memory_dir / "pref.md").write_text("Alice likes latte")

        session_ctx: dict[str, Any] = {"agent_env": {}}
        adapter.inject(task.sessions[0], session_ctx)

        mounts = session_ctx["memory_mounts"]
        assert len(mounts) == 1
        assert mounts[0].host_path == str(Path(adapter.memory_dir).resolve())
        assert mounts[0].container_path == CONTAINER_MEMORY_DIR

    def test_inject_is_recorded_as_op(self, tmp_path: Path) -> None:
        """inject 必须记进 memory_ops，且不是 skip。"""
        from dumemeval.adapters.directory import DirectoryMemoryAdapter

        adapter = DirectoryMemoryAdapter(MemorySpec(name="d", type="directory", path=str(tmp_path / "mem")))
        task = _task()
        adapter.setup(task)
        adapter.inject(task.sessions[0], {"agent_env": {}})

        inject_ops = [op for op in adapter.all_ops() if op.op == "inject"]
        assert inject_ops, "inject 未记录到 memory_ops"
        assert "skip" not in inject_ops[0].content.lower(), f"inject 走了 skip 分支：{inject_ops[0].content}"


class TestHermesBuiltinInjection:
    def test_declares_memories_and_config_mounts(self, tmp_path: Path) -> None:
        from dumemeval.adapters.hermes_builtin import HermesBuiltinMemoryAdapter

        adapter = HermesBuiltinMemoryAdapter(
            MemorySpec(
                name="h",
                type="hermes_builtin",
                path=str(tmp_path / "mem"),
                config={"base_url": "https://gw.example/v1", "api_key": "k", "model": "m"},
            )
        )
        task = _task()
        adapter.setup(task)
        session_ctx: dict[str, Any] = {"agent_env": {}}
        adapter.inject(task.sessions[0], session_ctx)

        targets = {m.container_path for m in session_ctx["memory_mounts"]}
        assert "/tmp/hermes/memories" in targets
        assert "/tmp/hermes/config.yaml" in targets


class TestExecutorsConsumeContract:
    """执行器必须消费 memory_mounts——mock 与真实用同一个契约。"""

    @pytest.mark.asyncio
    async def test_mock_runner_reports_injected_files(self, tmp_path: Path) -> None:
        from dumemeval.adapters.directory import DirectoryMemoryAdapter
        from dumemeval.execution.mock import MockRunner

        adapter = DirectoryMemoryAdapter(MemorySpec(name="d", type="directory", path=str(tmp_path / "mem")))
        task = _task()
        adapter.setup(task)
        (adapter.memory_dir / "pref.md").write_text("Alice likes latte")

        session_ctx: dict[str, Any] = {"agent_env": {}}
        adapter.inject(task.sessions[0], session_ctx)
        await MockRunner().run_session(task.sessions[0], session_ctx)

        injected = session_ctx["mock_injected_files"]
        assert any("pref.md" in name for name in injected)

    @pytest.mark.asyncio
    async def test_mock_runner_reports_agent_env(self, tmp_path: Path) -> None:
        """mock 同样消费 agent_env 契约（真实执行时经 TrialConfig.environment.env 进容器）。"""
        from dumemeval.adapters.directory import DirectoryMemoryAdapter
        from dumemeval.execution.mock import MockRunner

        adapter = DirectoryMemoryAdapter(MemorySpec(name="d", type="directory", path=str(tmp_path / "mem")))
        task = _task()
        adapter.setup(task)

        session_ctx: dict[str, Any] = {"agent_env": {}}
        adapter.inject(task.sessions[0], session_ctx)
        await MockRunner().run_session(task.sessions[0], session_ctx)

        assert session_ctx["mock_agent_env"]["DUMEMEVAL_MEMORY_DIR"] == "/app/memory"

    @pytest.mark.asyncio
    async def test_mock_runner_merges_env_extra(self, tmp_path: Path) -> None:
        from dumemeval.execution.mock import MockRunner
        from dumemeval.models import SessionSpec

        session = SessionSpec(id=1, instruction="x", env_extra={"FOO": "bar"})
        session_ctx: dict[str, Any] = {"agent_env": {"KEEP": "1"}}
        await MockRunner().run_session(session, session_ctx)
        assert session_ctx["mock_agent_env"]["FOO"] == "bar"
        assert session_ctx["mock_agent_env"]["KEEP"] == "1"

    @pytest.mark.asyncio
    async def test_mock_runner_missing_mount_raises(self, tmp_path: Path) -> None:
        from dumemeval.execution.mock import MockRunner
        from dumemeval.models import MemoryMount, SessionSpec

        session_ctx: dict[str, Any] = {
            "memory_mounts": [MemoryMount(host_path=str(tmp_path / "missing"), container_path="/app/memory")]
        }
        with pytest.raises(FileNotFoundError, match="memory_mounts"):
            await MockRunner().run_session(SessionSpec(id=1, instruction="x"), session_ctx)

    @pytest.mark.asyncio
    async def test_mock_runner_emits_trial_dir_when_provided(self, tmp_path: Path) -> None:
        from dumemeval.execution.mock import MockRunner
        from dumemeval.models import SessionSpec

        trial = tmp_path / "trial"
        trial.mkdir()
        session_ctx: dict[str, Any] = {
            "mock_trial_dir": trial,
            "instruction_suffix": "hint",
            "task_name": "t",
            "agent_memory_dir": "/app/memory",
        }
        await MockRunner().run_session(SessionSpec(id=1, instruction="x"), session_ctx)
        assert session_ctx["trial_dir"] == trial
        assert session_ctx["mock_instruction_suffix"] == "hint"
        assert session_ctx["mock_task_name"] == "t"
        assert session_ctx["mock_agent_memory_dir"] == "/app/memory"

    def test_harbor_bridge_maps_mounts_without_product_names(self, tmp_path: Path) -> None:
        """HarborBridge 从 memory_mounts 转 bind mounts，不认识任何产品名。"""
        import inspect

        from dumemeval.execution import harbor_bridge

        source = inspect.getsource(harbor_bridge)
        assert "hermes_memory_mount" not in source, "执行层不应认识产品特定键名"
        assert "hermes_config_mount" not in source
        assert "memory_mounts" in source, "执行层应消费统一的 memory_mounts 契约"
