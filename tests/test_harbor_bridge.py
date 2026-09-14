"""测试：execution 层（HarborBridge + trial_config + MemoryTransfer）。

拆分后：
- HarborBridge 测试：用 HarborConfig（pydantic）+ mock Trial
- trial_config 测试：纯函数构建
- MemoryTransfer 测试：收集/注入（独立于 HarborBridge）
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.execution.harbor_bridge import HarborBridge
from dumemeval.execution.trial_config import (
    HarborAgentConfig,
    HarborConfig,
    HarborEnvironmentConfig,
    MountConfig,
    build_trial_config,
)
from dumemeval.lifecycle.memory_transfer import CONTAINER_MEMORY_TARGET, MemoryTransfer
from dumemeval.models import SessionSpec

# 需要 Harbor 执行链（Fake 对象模拟 Harbor 类型）——归 integration 层
pytestmark = pytest.mark.integration


def _harbor_installed() -> bool:
    """Harbor 是可选 extra：只装 --extra dev 的贡献者不该看到红。"""
    try:
        import harbor  # noqa: F401
        from harbor.models.trajectories.trajectory import Trajectory  # noqa: F401
    except ImportError:
        return False
    return True


requires_harbor = pytest.mark.skipif(
    not _harbor_installed(),
    reason="需要 Harbor（uv sync --extra harbor）；贡献 adapter/数据集不需要",
)


class FakeTrialResult:
    """模拟 Harbor TrialResult（含官方 compute_token_cost_totals 接口）。"""

    def __init__(
        self,
        rewards: dict[str, Any] | float | None = None,
        exception: object | None = None,
        token_totals: tuple[int | None, int | None, int | None, float | None] | None = None,
    ) -> None:
        self.verifier_result = SimpleNamespace(rewards=rewards or {}, is_success=None)
        self.exception_info = exception
        # 默认返回 (None, None, None, None)，与真实 AgentContext 为空时的语义一致
        self._token_totals = token_totals or (None, None, None, None)

    def compute_token_cost_totals(
        self,
    ) -> tuple[int | None, int | None, int | None, float | None]:
        return self._token_totals


class FakeTrial:
    run: AsyncMock

    def __init__(self, trial_dir: Path) -> None:
        self.paths = SimpleNamespace(trial_dir=trial_dir)


def _write_trajectory(trial_dir: Path, agent_messages: list[str]) -> None:
    """写一份最小可用的 ATIF trajectory.json（含若干 agent 文本 step）。"""
    agent_dir = trial_dir / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    steps = [{"step_id": i + 1, "source": "agent", "message": msg} for i, msg in enumerate(agent_messages)]
    (agent_dir / "trajectory.json").write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "agent": {"name": "claude-code", "version": "test"},
                "steps": steps,
            }
        )
    )


@pytest.fixture
def bridge(tmp_path: Path) -> HarborBridge:
    from dumemeval.execution.task_dir import TaskDirGenerator

    return HarborBridge(
        config=HarborConfig(trials_dir="trials", agent=HarborAgentConfig(name="nop")),
        task_dir_generator=TaskDirGenerator(tasks_root=str(tmp_path / "tasks")),
    )


class TestParseTrialResult:
    def test_rewards_dict(self, bridge: HarborBridge, tmp_path: Path) -> None:
        """reward 原样透传；success 不再由 reward 推导（no-op verifier 下 reward 无判分含义）。"""
        result = FakeTrialResult(rewards={"total": 1.0, "memory_hit": 1.0})
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), result, tmp_path)
        assert outcome.reward == 1.0
        # 无异常 + 有 observation（tmp_path 下无 trajectory → success=False 是新语义）
        assert outcome.success is False

    def test_rewards_float(self, bridge: HarborBridge, tmp_path: Path) -> None:
        result = FakeTrialResult(rewards=0.0)
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), result, tmp_path)
        assert outcome.reward == 0.0
        assert outcome.success is False

    def test_exception(self, bridge: HarborBridge, tmp_path: Path) -> None:
        exc = SimpleNamespace(exception_type="RuntimeError", exception_message="boom")
        result = FakeTrialResult(rewards=None, exception=exc)
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), result, tmp_path)
        assert outcome.error == "RuntimeError: boom"
        assert outcome.success is False  # 有异常 → 不成功

    def test_none_result(self, bridge: HarborBridge, tmp_path: Path) -> None:
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), None, tmp_path)
        assert outcome.error == "trial result is None"

    def test_none_trial_dir(self, bridge: HarborBridge) -> None:
        """trial_dir 为 None（如 trial.paths 缺失）时不应崩溃，
        但 observation 为空 → success=False（没有可判分的输出）。"""
        result = FakeTrialResult(rewards={"total": 1.0})
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), result, None)
        assert outcome.observation == ""
        assert outcome.success is False

    @requires_harbor
    def test_extracts_agent_output_from_trajectory(self, bridge: HarborBridge, tmp_path: Path) -> None:
        """核心修复：agent 最终输出应从 trial_dir/agent/trajectory.json 提取，
        而不是像之前那样恒为空字符串。"""
        _write_trajectory(tmp_path, ["thinking...", "The final answer is 42."])
        result = FakeTrialResult(rewards={"total": 1.0})
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), result, tmp_path)
        assert outcome.observation == "The final answer is 42."

    def test_missing_trajectory_leaves_empty_observation(self, bridge: HarborBridge, tmp_path: Path) -> None:
        """trajectory.json 不存在时不伪造数据，observation 保持空字符串。"""
        result = FakeTrialResult(rewards={"total": 1.0})
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), result, tmp_path)
        assert outcome.observation == ""

    def test_token_totals_populate_outcome(self, bridge: HarborBridge, tmp_path: Path) -> None:
        """compute_token_cost_totals() 的结果应回填到 SessionOutcome.tokens_in/out。"""
        result = FakeTrialResult(rewards={"total": 1.0}, token_totals=(120, 20, 50, 0.01))
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), result, tmp_path)
        assert outcome.tokens_in == 120
        assert outcome.tokens_out == 50

    def test_token_totals_none_defaults_to_zero(self, bridge: HarborBridge, tmp_path: Path) -> None:
        """AgentContext 为空（无 token 数据）时保持 SessionOutcome 默认值 0，不报错。"""
        result = FakeTrialResult(rewards={"total": 1.0})
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), result, tmp_path)
        assert outcome.tokens_in == 0
        assert outcome.tokens_out == 0

    def test_no_compute_token_cost_totals_method(self, bridge: HarborBridge, tmp_path: Path) -> None:
        """trial_result 没有 compute_token_cost_totals（旧/不兼容对象）时优雅降级。"""
        result = SimpleNamespace(
            verifier_result=SimpleNamespace(rewards={"total": 1.0}, is_success=None),
            exception_info=None,
        )
        outcome = bridge._parse_trial_result(SessionSpec(id=1, instruction="x"), result, tmp_path)
        assert outcome.tokens_in == 0
        assert outcome.tokens_out == 0


class TestTrialConfigBuilder:
    def test_basic_config(self) -> None:
        cfg = build_trial_config(
            HarborConfig(trials_dir="trials", agent=HarborAgentConfig(name="claude-code", model="m1")),
            SessionSpec(id=1, instruction="x"),
            Path("/tmp/task"),
        )
        assert cfg["task"]["path"] == "/tmp/task"
        assert cfg["agent"]["name"] == "claude-code"
        assert cfg["agent"]["model_name"] == "m1"

    def test_memory_dir_injected(self) -> None:
        cfg = build_trial_config(
            HarborConfig(),
            SessionSpec(id=1, instruction="x"),
            Path("/tmp/task"),
            memory_dir=CONTAINER_MEMORY_TARGET,
        )
        assert cfg["agent"]["kwargs"] == {"memory_dir": CONTAINER_MEMORY_TARGET}

    def test_mounts_included(self) -> None:
        cfg = build_trial_config(
            HarborConfig(
                environment=HarborEnvironmentConfig(
                    mounts=[
                        MountConfig(source="/host/mem", target=str(CONTAINER_MEMORY_TARGET)),
                    ]
                )
            ),
            SessionSpec(id=1, instruction="x"),
            Path("/tmp/task"),
        )
        assert cfg["environment"]["mounts"] == [
            {"type": "bind", "source": "/host/mem", "target": CONTAINER_MEMORY_TARGET}
        ]

    def test_agent_env_merged_into_environment_env(self) -> None:
        """adapter/runner 注入的 agent_env 进 environment.env（此前通道断链）。"""
        cfg = build_trial_config(
            HarborConfig(),
            SessionSpec(id=1, instruction="x"),
            Path("/tmp/task"),
            agent_env={"DUMEMEVAL_MEMORY_DIR": str(CONTAINER_MEMORY_TARGET)},
        )
        assert cfg["environment"]["env"] == {"DUMEMEVAL_MEMORY_DIR": str(CONTAINER_MEMORY_TARGET)}

    def test_agent_env_overrides_yaml_env(self) -> None:
        """合并优先级：yaml execution.environment.env 为底，agent_env 覆盖。"""
        cfg = build_trial_config(
            HarborConfig(environment=HarborEnvironmentConfig(env={"K": "yaml", "ONLY_YAML": "1"})),
            SessionSpec(id=1, instruction="x"),
            Path("/tmp/task"),
            agent_env={"K": "agent"},
        )
        assert cfg["environment"]["env"] == {"K": "agent", "ONLY_YAML": "1"}

    def test_env_omitted_when_empty(self) -> None:
        """无 env 配置时 environment 段不出现 env 键（保持既有 TrialConfig 兼容）。"""
        cfg = build_trial_config(
            HarborConfig(),
            SessionSpec(id=1, instruction="x"),
            Path("/tmp/task"),
        )
        assert "env" not in cfg["environment"]

    def test_temperature_and_max_tokens_in_kwargs(self) -> None:
        cfg = build_trial_config(
            HarborConfig(agent=HarborAgentConfig(temperature=0.2, max_tokens=1024)),
            SessionSpec(id=1, instruction="x"),
            Path("/tmp/task"),
        )
        assert cfg["agent"]["kwargs"]["temperature"] == 0.2
        assert cfg["agent"]["kwargs"]["max_tokens"] == 1024

    def test_default_temperature_not_in_kwargs(self) -> None:
        """未显式配置时不写 kwargs，让 Harbor 走自己的默认。"""
        cfg = build_trial_config(
            HarborConfig(),
            SessionSpec(id=1, instruction="x"),
            Path("/tmp/task"),
        )
        assert "kwargs" not in cfg["agent"]


class TestMemoryTransfer:
    def test_inject_transfer_memory(self, tmp_path: Path) -> None:
        """有 transfer memory 时注入到挂载源目录。"""
        transfer = tmp_path / "transfer"
        transfer.mkdir()
        (transfer / "alice.md").write_text("Alice likes latte")
        ctx = {"memory_transfer_dir": str(transfer)}

        mt = MemoryTransfer(transfer_dir=transfer, mount_source=tmp_path / "mount")
        memory_dir = mt.inject(ctx)
        assert memory_dir == CONTAINER_MEMORY_TARGET
        assert (tmp_path / "mount" / "alice.md").exists()

    def test_inject_no_memory(self, tmp_path: Path) -> None:
        """无 transfer memory 时返回 None。"""
        empty = tmp_path / "empty"
        empty.mkdir()
        ctx = {"memory_transfer_dir": str(empty)}

        mt = MemoryTransfer(transfer_dir=empty, mount_source=tmp_path / "mount")
        assert mt.inject(ctx) is None

    def test_collect_memory(self, tmp_path: Path) -> None:
        """从 trial 目录收集 claude auto-memory 到 transfer。"""
        trial_dir = tmp_path / "trial"
        memory_dir = trial_dir / "agent" / "sessions" / "projects" / "-workspace" / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "alice.md").write_text("# Alice likes latte")

        mt = MemoryTransfer(transfer_dir=tmp_path / "transfer", mount_source=tmp_path / "mount")
        copied = mt.collect(trial_dir, SessionSpec(id=1, instruction="x"))
        collected = list((tmp_path / "transfer").glob("*.md"))
        assert copied == 1
        assert len(collected) == 1
        assert "-workspace__alice.md" in collected[0].name


class TestRunSession:
    @requires_harbor
    @pytest.mark.asyncio
    async def test_run_session_mock_trial(self, bridge: HarborBridge, tmp_path: Path) -> None:
        """mock Harbor Trial，验证 run_session 全流程。"""
        session = SessionSpec(id=1, instruction="记住偏好")

        fake_trial = FakeTrial(trial_dir=tmp_path / "trial")
        fake_result = FakeTrialResult(rewards={"total": 1.0})
        fake_trial.run = AsyncMock(return_value=fake_result)
        _write_trajectory(tmp_path / "trial", ["agent did the task"])

        with patch("harbor.trial.trial.Trial.create", new=AsyncMock(return_value=fake_trial)):
            outcome = await bridge.run_session(
                session,
                {"memory_transfer_dir": str(tmp_path / "transfer"), "task_name": "locomo_0"},
            )

        assert outcome.success is True
        assert outcome.reward == 1.0
        # task 目录应生成（按 task_name 隔离，跨 task 并行防冲突）
        assert (tmp_path / "tasks" / "locomo_0__session_1" / "instruction.md").exists()


class TestArtifacts:
    def test_collect_artifacts(self, bridge: HarborBridge, tmp_path: Path) -> None:
        """按 session.artifacts 收集产物文件。"""
        from dumemeval.models import SessionSpec

        session = SessionSpec(id=1, instruction="x", artifacts=["output.txt"])
        trial_dir = tmp_path / "trial"
        agent_dir = trial_dir / "agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "output.txt").write_text("hello")

        artifacts = bridge._collect_artifacts(session, trial_dir)
        assert "output.txt" in artifacts
        assert artifacts["output.txt"].read_text() == "hello"

    def test_no_artifacts_declared(self, bridge: HarborBridge, tmp_path: Path) -> None:
        session = SessionSpec(id=1, instruction="x")
        assert bridge._collect_artifacts(session, tmp_path / "trial") == {}

    def test_missing_artifact_ignored(self, bridge: HarborBridge, tmp_path: Path) -> None:
        session = SessionSpec(id=1, instruction="x", artifacts=["nope.txt"])
        trial_dir = tmp_path / "trial"
        (trial_dir / "agent").mkdir(parents=True)
        assert bridge._collect_artifacts(session, trial_dir) == {}
