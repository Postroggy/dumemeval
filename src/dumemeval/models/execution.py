from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SessionOutcome(BaseModel):
    """单个 session 的执行结果。

    由 ``SessionExecutor`` 产出、``metrics`` 消费——放在 models 层，
    避免 metrics 反向依赖 execution 实现（见 GOVERNANCE 分层禁区）。
    """

    session_id: int = Field(ge=1)
    success: bool = False
    reward: float = 0.0
    observation: str = ""
    artifacts: dict[str, Path] = Field(default_factory=dict)
    error: str | None = None
    tokens_in: int = Field(default=0, ge=0, description="输入 token 数")
    tokens_out: int = Field(default=0, ge=0, description="输出 token 数")
    trial_dir: str | None = Field(
        default=None,
        description="本 session 对应的 Harbor trial 目录（含 agent/trajectory.json 等原始产物）；mock 或未产出时 None",
    )
    query: str | None = Field(
        default=None,
        description="该 session 对应的 benchmark 问题原文；非问答 session 为 None",
    )


class MemoryMount(BaseModel):
    """一条 memory 挂载声明（host 目录/文件 → agent 环境内路径）。

    adapter 在 ``inject`` 里通过 ``adapters.base.declare_mount`` 追加到
    ``session_ctx["memory_mounts"]``；执行器（Harbor / Mock）统一消费——
    执行层因此不必认识任何 memory 产品的键名。
    """

    host_path: str = Field(description="host 侧路径（目录或文件，必须已存在）")
    container_path: str = Field(description="agent 环境内的绝对路径")


MemoryOpName = Literal["setup", "inject", "snapshot", "add", "replace", "remove", "search"]
MEMORY_WRITE_OPS: frozenset[str] = frozenset({"add", "replace", "remove"})
MEMORY_READ_OPS: frozenset[str] = frozenset({"search"})


class MemoryOp(BaseModel):
    """观测到的 memory 读写操作（Quality / Efficiency / Trace 共用）。

    ``op`` 是框架词表，不是产品 API 名。adapter 必须在记录时映射过来：
    写入类用 add/replace/remove，检索用 search；setup/inject/snapshot 是框架动作。
    """

    session_id: int = Field(ge=0)
    op: MemoryOpName
    content: str = Field(default="", description="写入/检索的内容")
    query: str = Field(default="", description="检索 query")
    timestamp: float = 0.0


class MemoryFact(BaseModel):
    """Quality 评测的事实单元（"该记住什么"）。"""

    fact: str = Field(description="事实内容")
    category: Literal["persona", "event", "preference", "fact"] = Field(
        default="fact", description="事实类别（persona / event / preference / fact）"
    )
