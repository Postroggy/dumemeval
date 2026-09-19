from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QualityResult(BaseModel):
    """Memory 本身质量指标（Quality）。

    ⚠️ 指标语义近似说明（当前实现的局限，勿过度解读）：
    - ``precision`` 实际是"含任一 GT fact 的 memory 文件占比"（文件级命中率）。
      一个文件覆盖多条 fact 只算 1 个相关文件；不是 HaluMem 官方那种
      基于逐条 memory 标注（该记/不该记）的 precision。
    - ``hallucination_rate = 1 - precision``，即"无关文件占比"。没有
      negative 样本（明确不该写入的内容标注）时，无法真正测幻觉，
      只能识别"与 GT 完全无关的写入"。
    - ``update_accuracy`` 当前无计算器实现，恒为 None（未测），报告应显示
      n/a 而非 0——待接入 HaluMem 式的更新操作级评测后才有值。
    """

    precision: float = Field(default=0.0, ge=0, le=1)
    recall: float = Field(default=0.0, ge=0, le=1)
    hallucination_rate: float = Field(default=0.0, ge=0, le=1)
    omission_rate: float = Field(default=0.0, ge=0, le=1)
    update_accuracy: float | None = Field(
        default=None, description="更新操作正确率；None = 未测（当前无计算器实现）"
    )
    details: list[dict[str, Any]] = Field(default_factory=list)


class UtilityResult(BaseModel):
    """Agent 任务表现指标（Utility）。"""

    task_success: bool = False
    success_rate: float = Field(default=0.0, ge=0, le=1)
    turns: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    memory_conditioned_gain: float = 0.0
    details: list[dict[str, Any]] = Field(default_factory=list)


class EfficiencyResult(BaseModel):
    """系统效率指标（Efficiency）。"""

    write_latency_ms: float = Field(default=0.0, ge=0)
    retrieval_latency_ms: float = Field(default=0.0, ge=0)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    details: list[dict[str, Any]] = Field(default_factory=list)


class TraceResult(BaseModel):
    """Agent 行为体检（Trace）：轨迹采到没、有没有真的用 memory、跑挂没。

    全部来自已采集数据（TaskExecution.sessions + memory_ops），不需要额外探测。
    ⚠️ ``memory_tool_used`` 只统计 agent 侧读写（add/replace/remove/search）；
    setup/inject/snapshot 是框架动作，不算 agent 用了 memory。
    """

    trace_captured_rate: float = Field(default=0.0, ge=0, le=1, description="observation 非空占比")
    empty_output_rate: float = Field(default=0.0, ge=0, le=1)
    error_rate: float = Field(default=0.0, ge=0, le=1)
    memory_tool_used: bool | None = Field(default=None, description="Observed memory use; None = unmeasured")
    memory_write_ops: int | None = Field(default=None, ge=0, description="Observed writes, a lower bound")
    memory_read_ops: int | None = Field(default=None, ge=0, description="Observed reads, a lower bound")
    details: list[dict[str, Any]] = Field(default_factory=list)
