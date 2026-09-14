"""判分基础：Verdict + BaseVerifier。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class Verdict(BaseModel):
    """统一判分结果（pydantic 约束）。"""

    label: str = Field(description='"CORRECT" / "WRONG" / "SKIPPED" 或 "pass" / "fail"')
    score: float = Field(default=0.0, ge=0, le=1)
    reason: str = ""
    raw: str = Field(default="", description="judge 原始输出")
    runs: int = Field(default=1, ge=1, description="LLM-as-Judge 实际运行次数")
    run_scores: list[float] = Field(default_factory=list, description="各次运行的 score")
    model_input: str | None = Field(default=None, description="judge user prompt（save_model_input 时填写）")

    @property
    def is_pass(self) -> bool:
        return self.score >= 0.5

    def __repr__(self) -> str:
        return f"<Verdict {self.label} score={self.score:.2f}>"


class BaseVerifier(ABC):
    """判分器基类。子类实现 verify()。"""

    name: str = "base"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @abstractmethod
    def verify(self, response: str, ground_truth: str, **ctx: Any) -> Verdict:
        """判分。

        Args:
            response: agent 的回答 / memory 内容
            ground_truth: 参考答案 / 期望事实
            ctx: 附加上下文（question/task/rubric 等）
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.name}>"
