"""评测协议（EvalProtocol 策略对象化）。

设计要点：
- protocol 不再是 Literal 字符串，而是策略对象
- 每个协议定义"session 序列如何编排 memory 生命周期"
- 注册表按名创建；SessionRunner 通过协议决定生命周期行为
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cache
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from ..models import SessionSpec


class EvalProtocol(ABC):
    """评测协议抽象：决定 session 序列如何编排 memory 生命周期。

    子类实现 validate()（配置校验）和 describe()（协议语义说明）。
    """

    name: ClassVar[str] = ""

    @abstractmethod
    def validate(self, n_sessions: int, memory_injects: list[bool]) -> None:
        """校验协议与 session 序列的相容性。

        Args:
            n_sessions: session 数量
            memory_injects: 每个 session 是否注入 memory

        Raises:
            ValueError: 协议与 session 序列不匹配
        """
        raise NotImplementedError

    def normalize_sessions(self, sessions: list[SessionSpec]) -> list[SessionSpec]:
        """协议对 session 序列的归一化（构建适配器产物后、validate 前调用）。

        原地修改并返回同一列表；默认恒等。协议需要强制 session 属性时覆写——
        如 test_only 强制 memory_inject=false，以兼容硬编码 memory_inject=True
        的 benchmark 适配器（适配器不知道协议，归一化归协议层）。
        """
        return sessions

    # ── 生命周期策略（runner 调用，协议决定）───────────────────────────

    def should_inject_memory(self, session_memory_inject: bool) -> bool:
        """协议是否允许跨 session memory 注入（MemoryTransfer 通道）。"""
        return session_memory_inject

    def should_collect_memory(self, session_memory_inject: bool) -> bool:
        """协议是否允许收集 memory（auto-memory 收集）。"""
        return session_memory_inject

    def should_adapter_inject(self, session_memory_inject: bool) -> bool:
        """协议是否允许 adapter 注入（env/mount 通道）。"""
        return session_memory_inject

    def should_snapshot(self, session_memory_inject: bool) -> bool:
        """协议是否允许快照 memory 状态。"""
        return session_memory_inject

    def describe(self) -> str:
        """协议语义说明（报告/日志用）。"""
        return self.name


class MemorySessionTransferProtocol(EvalProtocol):
    """★ 核心协议：session 间 memory 传递。

    session1 记住 → collect → session2 应用注入的 memory。
    """

    name = "memory_session_transfer"

    def validate(self, n_sessions: int, memory_injects: list[bool]) -> None:
        if n_sessions < 2:
            raise ValueError(f"protocol={self.name!r} requires >= 2 sessions, got {n_sessions}")
        if not any(memory_injects):
            raise ValueError(f"protocol={self.name!r} requires at least one memory_inject session")

    # 跨 session 传递：所有 memory 通道开启
    def should_inject_memory(self, session_memory_inject: bool) -> bool:
        return True

    def should_collect_memory(self, session_memory_inject: bool) -> bool:
        return True

    def should_adapter_inject(self, session_memory_inject: bool) -> bool:
        return True

    def should_snapshot(self, session_memory_inject: bool) -> bool:
        return True

    def describe(self) -> str:
        return "跨 session memory 传递（session1 记 → session2 用）"


class TestOnlyProtocol(EvalProtocol):
    """只测协议：无 memory 注入，测 agent 裸能力。"""

    name = "test_only"

    def validate(self, n_sessions: int, memory_injects: list[bool]) -> None:
        if any(memory_injects):
            raise ValueError(f"protocol={self.name!r} requires all sessions memory_inject=false")

    def normalize_sessions(self, sessions: list[SessionSpec]) -> list[SessionSpec]:
        """只测：无论来源如何，一律关闭 memory 注入（适配器产物硬编码 True 也归零）。"""
        for s in sessions:
            s.memory_inject = False
        return sessions

    # 只测：所有 memory 生命周期通道关闭
    def should_inject_memory(self, session_memory_inject: bool) -> bool:
        return False

    def should_collect_memory(self, session_memory_inject: bool) -> bool:
        return False

    def should_adapter_inject(self, session_memory_inject: bool) -> bool:
        return False

    def should_snapshot(self, session_memory_inject: bool) -> bool:
        return False

    def describe(self) -> str:
        return "只测（无 memory 注入，测 agent 裸能力）"


class MemoryTrainBackupTestProtocol(EvalProtocol):
    """训练→备份→恢复→测试协议。

    ⚠️ experimental：备份/恢复语义尚未在 runner 实现。当前生命周期行为与
    memory_session_transfer 相同（未覆写任何 should_* 开关）——用它跑出的
    结果等同 transfer，不要把它当 backup/restore 的验证。
    """

    name = "memory_train_backup_test"

    def validate(self, n_sessions: int, memory_injects: list[bool]) -> None:
        if n_sessions < 2:
            raise ValueError(f"protocol={self.name!r} requires >= 2 sessions, got {n_sessions}")

    def describe(self) -> str:
        return "训练→备份→恢复→测试（experimental：行为等同 memory_session_transfer，backup/restore 未实现）"


# ── 注册表 ──────────────────────────────────────────────────────────────────

_PROTOCOL_REGISTRY: dict[str, type[EvalProtocol]] = {
    MemorySessionTransferProtocol.name: MemorySessionTransferProtocol,
    TestOnlyProtocol.name: TestOnlyProtocol,
    MemoryTrainBackupTestProtocol.name: MemoryTrainBackupTestProtocol,
}


@cache
def get_protocol(name: str) -> EvalProtocol:
    """按名取协议实例（协议无状态，lru_cache 共享单例）。"""
    cls = _PROTOCOL_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown protocol: {name!r}. Supported: {list(_PROTOCOL_REGISTRY)}")
    return cls()


def register_protocol(cls: type[EvalProtocol]) -> type[EvalProtocol]:
    """注册自定义协议（扩展点，与 adapters 的 register_adapter 同范式）。"""
    _PROTOCOL_REGISTRY[cls.name] = cls
    get_protocol.cache_clear()
    return cls


def protocol_names() -> list[str]:
    """所有协议名。"""
    return list(_PROTOCOL_REGISTRY)
