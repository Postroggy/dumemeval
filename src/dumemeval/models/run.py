"""Run 级模型：整批评测摘要、溯源、跨 run 比较。

与 ``models/results.py`` 里的 task 级结果（TaskResult / MetricReport）分层：
这里是「一次 run」和「多次 run 之间」的概念。不依赖 core/ 或其他层，避免成环。
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from .results import BenchmarkResult


class TaskEnvSpec(BaseModel):
    """任务环境（agentic env server）配置——config 层与 environments 层共用。"""

    type: str = Field(default="http", description="provider 名（environments 注册表）")
    base_url: str | None = Field(default=None, description="环境 server 地址")
    config: dict[str, object] = Field(default_factory=dict, description="provider 特定配置")


# ── 溯源（provenance.py 的函数消费这两个模型）────────────────────────────────


class GitSnapshot(BaseModel):
    """仓库快照；不在 git 仓库内时 commit 为 None。"""

    commit: str | None = None
    branch: str | None = None
    dirty: bool = False


class RunProvenance(BaseModel):
    """一次评测的可复现元数据（写入 experiment_config.json 与报告）。"""

    run_id: str = Field(
        default="",
        description="实验变量派生的稳定身份（benchmark+data.name+protocol+memory.type+memory_instruction+agent.runtime）。用于结果↔测试追溯，不参与 compare 准入",
    )
    mock: bool = False
    reproduce: str = ""
    git: GitSnapshot = Field(default_factory=GitSnapshot)
    n_concurrent: int = 1
    judging_type: str = ""
    judging_model: str | None = None
    judging_num_runs: int = 1
    judging_skip_failed: bool = False
    config_path: str = ""
    output_dir: str = ""


# ── 整批摘要 ────────────────────────────────────────────────────────────────


class TaskSummary(BaseModel):
    """单 task 聚合摘要。"""

    task_name: str
    n_sessions: int = 0
    n_success: int = 0
    report_dir: str = ""
    benchmark_f1: float | None = None


class RunSummary(BaseModel):
    """整批（多 task）评测的聚合摘要（落盘 summary.md/json）。"""

    run_id: str = Field(default="", description="实验变量派生的稳定身份（与 provenance.run_id 同源）")
    experiment_name: str = ""
    generated_at: str = ""
    n_tasks: int
    n_concurrent: int = 1
    mock: bool = False
    quality_recall_avg: float | None = None
    quality_precision_avg: float | None = None
    utility_success_rate_avg: float = 0.0
    benchmark: BenchmarkResult | None = None
    per_task: list[TaskSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(
        default_factory=dict,
        description="run 级扁平指标（pooled benchmark + 跨 task 平均）；compare 直接 diff 这里",
    )


# ── 跨 run 比较 ─────────────────────────────────────────────────────────────


class MetricDirection(StrEnum):
    """指标方向：决定 delta 是变好还是变差。"""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class RunRef(BaseModel):
    """一个已落盘 run 的引用（compare 的输入单元）。"""

    label: str = Field(description="展示名（默认取目录名）")
    path: Path
    summary: RunSummary
    provenance: RunProvenance | None = None


class MetricDelta(BaseModel):
    """单个指标在多个 run 之间的取值与差值。

    缺值记 None（「没测」≠「测得 0」）；无 baseline 时 delta 为 None，只排名。
    """

    metric: str
    direction: MetricDirection = MetricDirection.HIGHER_IS_BETTER
    values: dict[str, float | None] = Field(default_factory=dict)
    baseline: str | None = None

    def delta(self, label: str) -> float | None:
        """相对 baseline 的差值；无 baseline 或任一侧缺值时 None。"""
        if self.baseline is None:
            return None
        base, current = self.values.get(self.baseline), self.values.get(label)
        if base is None or current is None:
            return None
        return current - base

    def improved(self, label: str) -> bool | None:
        """是否变好（按 direction 判定）；无 delta 时 None。"""
        diff = self.delta(label)
        if diff is None:
            return None
        if self.direction is MetricDirection.LOWER_IS_BETTER:
            return diff < 0
        return diff > 0

    def best_label(self) -> str | None:
        """表现最好的 run（higher/lower 各取 max/min）；全缺值时 None。"""
        present = {label: value for label, value in self.values.items() if value is not None}
        if not present:
            return None
        if self.direction is MetricDirection.LOWER_IS_BETTER:
            return min(present, key=lambda key: present[key])
        return max(present, key=lambda key: present[key])


class RunComparison(BaseModel):
    """一次跨 run 比较的完整结果。"""

    labels: list[str] = Field(default_factory=list)
    baseline: str | None = None
    deltas: list[MetricDelta] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    has_mock: bool = False

    def delta_for(self, metric: str) -> MetricDelta | None:
        for item in self.deltas:
            if item.metric == metric:
                return item
        return None
