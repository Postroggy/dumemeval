from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class VerifierSpec(BaseModel):
    """判分配置（LLM judge / 规则）。"""

    type: Literal["llm_judge", "rule"] = Field(default="llm_judge")
    ground_truth: str = Field(default="", description="参考答案")
    prompt: Literal["memory_qa", "memory_quality", "task_success", "math_equivalence", "search_grader"] = (
        Field(default="memory_quality")
    )
    timeout_sec: float = Field(default=600.0, ge=0, description="verifier 超时（秒）")


class SessionSpec(BaseModel):
    """单个 session 的定义。一个 session = 一次 agent 在隔离环境中的运行。"""

    id: int = Field(ge=1, description="session 序号（1-based）")
    instruction: str = Field(description="给 agent 的任务指令")
    verifier: VerifierSpec | None = Field(
        default=None, description="该 session 的判分配置（LLM judge / 规则）"
    )
    memory_inject: bool = Field(default=True, description="该 session 是否注入 memory")
    artifacts: list[str] = Field(default_factory=list, description="需要收集的产出文件")
    env_extra: dict[str, Any] = Field(default_factory=dict, description="环境附加配置")
    query: str | None = Field(
        default=None,
        description=(
            "该 session 对应的 benchmark 问题/查询原文（与 task.data 里的 "
            "question/query 字段完全一致）。用于 outputs_from_execution 精确匹配 "
            "agent 输出 ↔ 问题，而不是按 session 在序列中的位置猜测——"
            "非问答类 session（如 memory 注入、ingest）留空即可。"
        ),
    )


class MemorySpec(BaseModel):
    """Memory 后端定义。

    directory: 内存型 memory 统一为目录语义（Claude Code 的 memory/、外挂目录）
    http:      外部 HTTP memory 服务（Mem0/Letta/自建 server）
    hermes_builtin: Hermes 官方内置 memory（$HERMES_HOME/memories/MEMORY.md + USER.md）
    everos:    EverOS 官方 /api/v1/memory/*
    其他 type：社区 ``register_adapter`` 注册的后端
    """

    name: str = Field(description="后端名（registry 用）")
    type: str = Field(
        default="directory",
        description="adapter 类型（adapters.registry；未知类型在 create_adapter 时报错）",
    )
    path: str | None = Field(
        default=None, description="directory/hermes_builtin 型：memory 目录路径（host 侧）"
    )
    base_url: str | None = Field(default=None, description="http 型：服务地址")
    user_id: str | None = Field(default=None, description="隔离键（多 run 共用后端时防交叉污染）")
    team_id: str = Field(default="default", description="(预留) 租户隔离 team_id")
    agent_id: str = Field(default="default", description="(预留) agent 标识")
    config: dict[str, Any] = Field(default_factory=dict, description="后端特定配置")


class EvalTask(BaseModel):
    """一个 multi-session 评测任务。"""

    name: str = Field(description="任务名（如 user-preference-memory）")
    description: str = ""
    sessions: list[SessionSpec] = Field(default_factory=list, description="按序执行，后者依赖前者")
    memory_ground_truth: str = Field(default="", description="Quality 评测：该记住什么")
    task_ground_truth: str = Field(default="", description="Utility 评测：任务成功标准")
    agent: dict[str, Any] = Field(default_factory=dict, description="agent 配置")
    data: dict[str, Any] = Field(default_factory=dict, description="任务数据引用")
    benchmark: str | None = Field(
        default=None, description="数据集指标计算器名（locomo / memoryarena_* / streammembench）"
    )
    memory_instruction: Literal["none", "location", "proactive"] = Field(
        default="none", description="是否告知 agent 持久记忆的存在（none=基线）"
    )
    task_environment: dict[str, Any] = Field(
        default_factory=dict,
        description="agentic 任务环境 {type, base_url, config}；空 = 纯文本任务",
    )

    def add_session(self, session: SessionSpec) -> None:
        """追加 session，自动编号。"""
        session.id = len(self.sessions) + 1
        self.sessions.append(session)
