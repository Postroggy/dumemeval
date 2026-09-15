"""Memory 后端适配器层。

设计要点：
- BaseMemoryAdapter 统一 memory 语义（目录型/HTTP 型都收敛）
- 生命周期显式化：setup → inject → snapshot → observe → teardown
- 注入契约：inject 必须写 memory_mounts（挂载）或 agent_env（服务地址），
  执行器统一消费，不认识具体产品（见 docs/adapters/memory-injection-contract.md）
- Quality 观测在 adapter 层（记录所有读写操作），不侵入 agent
- registry 懒加载：缺失依赖的后端不影响其他后端
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from ..models import EvalTask, MemoryMount, MemoryOp, MemoryOpName, MemorySpec, SessionOutcome, SessionSpec

# session_ctx 里的注入通道键名（执行器消费）
MEMORY_MOUNTS_KEY = "memory_mounts"
AGENT_ENV_KEY = "agent_env"


def declare_mount(session_ctx: dict[str, Any], host_path: str | Path, container_path: str) -> None:
    """声明一条 memory 挂载（host → agent 环境内路径）。

    adapter 在 ``inject`` 里调用；执行器（Harbor / Mock）读
    ``session_ctx["memory_mounts"]`` 统一处理——执行层不需要认识
    任何 memory 产品的专有键名。
    """
    mounts: list[MemoryMount] = session_ctx.setdefault(MEMORY_MOUNTS_KEY, [])
    mounts.append(MemoryMount(host_path=str(Path(host_path).resolve()), container_path=container_path))


class BaseMemoryAdapter(ABC):
    """Memory 后端统一抽象。

    子类实现 directory（目录型）或 http（HTTP 服务型）。
    评测编排层只依赖本类的方法，不感知具体后端。

    ``type_name`` 是注册键（registry 用，对应 ``MemorySpec.type``），
    与实例属性 ``name``（运行名，来自 spec.name）区分。
    """

    type_name: ClassVar[str] = ""

    def __init__(self, spec: MemorySpec):
        self.spec = spec
        self.name = spec.name
        self._ops: list[MemoryOp] = []

    # ── 生命周期（由 SessionRunner 调用）───────────────────────────────────

    @abstractmethod
    def setup(self, task: EvalTask) -> None:
        """评测开始前准备 memory 空间（建目录 / 初始化连接）。"""

    @abstractmethod
    def inject(self, session: SessionSpec, session_ctx: dict[str, Any]) -> None:
        """把 memory 注入 agent 环境。

        **必须**至少写一条注入通道，否则 memory 到不了 agent（静默失败）：

        - 目录/文件型：``declare_mount(session_ctx, host_path, container_path)``
        - 服务型：写 ``session_ctx["agent_env"]``（服务地址、user_id 等）

        执行器（Harbor / Mock）只消费这两个通道，不认识具体产品。
        契约由 ``tests/test_adapter_contract.py`` 强制。
        """

    @abstractmethod
    def snapshot(self, session: SessionSpec, snapshot_dir: Path) -> Path:
        """快照当前 memory 状态（跨 session 保留 / Quality 分析用）。"""

    @abstractmethod
    def observe(self, session: SessionSpec) -> list[MemoryOp]:
        """观测该 session 期间发生的 memory 读写。"""

    def observe_execution(self, session: SessionSpec, outcome: SessionOutcome) -> None:
        """Collect optional runtime evidence after a session; existing adapters need no hook."""
        return None

    def seed_history(self, task: EvalTask) -> None:
        """评测前注入历史对话（可选覆写；默认 no-op）。

        benchmark 评测需要"先把历史记忆灌进被测 memory"时（如 Hermes 的
        L0 对话灌入），adapter 覆写本方法从 task.data 取对话并写入。
        """
        return None

    def memory_usage_hint(self) -> str | None:
        """用本 adapter 的通道语言描述「memory 在哪、怎么用」（供 memory_instruction）。

        None = 该后端没有可告知的位置（如纯被动注入）。返回的是位置/方式描述，
        不含行为要求（「主动读写」由 memory_instruction 模式统一措辞）。
        """
        return None

    def teardown(self) -> None:
        """评测结束后清理（可选覆写；默认清空观测记录）。"""
        self._ops.clear()

    # ── 共享工具 ────────────────────────────────────────────────────────────

    def _record(self, op: MemoryOpName, session_id: int, content: str = "", query: str = "") -> None:
        self._ops.append(
            MemoryOp(
                session_id=session_id,
                op=op,
                content=content,
                query=query,
            )
        )

    def all_ops(self) -> list[MemoryOp]:
        return list(self._ops)

    def read_memory_files(self) -> dict[str, str]:
        """Read current memory contents for Quality scoring. Default: none."""
        return {}

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} type={self.spec.type}>"
