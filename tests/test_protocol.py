"""测试：评测协议（EvalProtocol 策略对象化）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.core.protocol import (
    EvalProtocol,
    MemorySessionTransferProtocol,
    MemoryTrainBackupTestProtocol,
    TestOnlyProtocol,
    get_protocol,
    protocol_names,
    register_protocol,
)


class TestMemorySessionTransfer:
    def test_requires_two_sessions(self) -> None:
        with pytest.raises(ValueError, match="requires >= 2 sessions"):
            MemorySessionTransferProtocol().validate(1, [True])

    def test_requires_memory_inject(self) -> None:
        with pytest.raises(ValueError, match="at least one memory_inject"):
            MemorySessionTransferProtocol().validate(2, [False, False])

    def test_valid(self) -> None:
        MemorySessionTransferProtocol().validate(2, [True, True])

    def test_normalize_sessions_identity(self) -> None:
        """transfer 协议不覆写归一化（基类恒等），不改注入标记。"""
        from dumemeval.models import SessionSpec

        sessions = [SessionSpec(id=1, instruction="s1", memory_inject=True)]
        assert MemorySessionTransferProtocol().normalize_sessions(sessions) == sessions
        assert sessions[0].memory_inject is True

    def test_describe(self) -> None:
        assert "跨 session" in MemorySessionTransferProtocol().describe()


class TestTestOnly:
    def test_requires_no_inject(self) -> None:
        with pytest.raises(ValueError, match="memory_inject=false"):
            TestOnlyProtocol().validate(2, [True, False])

    def test_valid(self) -> None:
        TestOnlyProtocol().validate(2, [False, False])

    def test_normalize_sessions_forces_false(self) -> None:
        """test_only 归一化：适配器硬编码 memory_inject=True 也一律归零。"""
        from dumemeval.models import SessionSpec

        sessions = [
            SessionSpec(id=1, instruction="s1", memory_inject=True),
            SessionSpec(id=2, instruction="s2", memory_inject=True),
        ]
        normalized = TestOnlyProtocol().normalize_sessions(sessions)
        assert all(not s.memory_inject for s in normalized)
        # 原地归一化后 validate 通过（构建后先归一化再校验的调用约定）
        TestOnlyProtocol().validate(len(normalized), [s.memory_inject for s in normalized])


class TestMemoryTrainBackupTest:
    def test_requires_two_sessions(self) -> None:
        with pytest.raises(ValueError, match="requires >= 2 sessions"):
            MemoryTrainBackupTestProtocol().validate(1, [True])

    def test_valid(self) -> None:
        MemoryTrainBackupTestProtocol().validate(3, [True, True, True])


class TestRegistry:
    def test_get_protocol(self) -> None:
        assert isinstance(get_protocol("memory_session_transfer"), MemorySessionTransferProtocol)
        assert isinstance(get_protocol("test_only"), TestOnlyProtocol)
        assert isinstance(get_protocol("memory_train_backup_test"), MemoryTrainBackupTestProtocol)

    def test_unknown_protocol_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown protocol"):
            get_protocol("bogus")

    def test_protocol_names(self) -> None:
        names = protocol_names()
        assert "memory_session_transfer" in names
        assert "test_only" in names
        assert "memory_train_backup_test" in names

    def test_register_protocol_is_the_extension_point(self) -> None:
        class _ToyProtocol(EvalProtocol):
            name = "toy_protocol"

            def validate(self, n_sessions: int, memory_injects: list[bool]) -> None:
                return None

        register_protocol(_ToyProtocol)
        get_protocol.cache_clear()
        try:
            assert isinstance(get_protocol("toy_protocol"), _ToyProtocol)
            assert "toy_protocol" in protocol_names()
        finally:
            from dumemeval.core import protocol as _prot

            _prot._PROTOCOL_REGISTRY.pop("toy_protocol", None)
            get_protocol.cache_clear()


class TestConfigIntegration:
    """协议对象与 ExperimentConfig 的集成（校验委托）。"""

    def test_config_uses_protocol_object(self, tmp_path: Path) -> None:
        from dumemeval.config import load_config

        p = tmp_path / "eval.yaml"
        p.write_text(
            """
experiment:
  name: demo
  protocol: test_only
memory:
  name: m
task:
  sessions:
    - instruction: "s1"
      memory_inject: false
"""
        )
        cfg = load_config(p)
        assert cfg.protocol_instance.name == "test_only"
