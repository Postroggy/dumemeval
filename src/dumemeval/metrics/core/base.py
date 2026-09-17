"""统一指标计算层：MetricCalculator 协议 + MetricsAggregator。

一次评测 → 多个计算器 → 一份聚合报告（result.metrics）。
Quality / Utility / Efficiency / Trace 指标走这个入口；benchmark 由 evaluation.scorer 负责。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ...models import (
    AgentOutput,
    BenchmarkResult,
    EfficiencyResult,
    EvalTask,
    MemoryFact,
    MetricReport,
    QualityResult,
    SampleResult,
    SessionOutcome,
    TaskExecution,
    TraceResult,
    UtilityResult,
)

MetricKind = Literal["quality", "utility", "efficiency", "trace", "benchmark"]


class MetricInput(BaseModel):
    """Typed facts available to cross-cutting metric calculators."""

    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True}

    task: EvalTask | None = None
    execution: TaskExecution | None = None
    samples: list[SampleResult] = Field(default_factory=list)
    benchmark: Any | None = None
    provided_outputs: list[AgentOutput] = Field(default_factory=list, alias="outputs")
    provided_outcomes: list[SessionOutcome] = Field(default_factory=list, alias="outcomes")
    memory_files: dict[str, str] = Field(default_factory=dict)
    ground_truth_facts: list[MemoryFact] = Field(default_factory=list)
    probe_events: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def outputs(self) -> list[AgentOutput]:
        if self.provided_outputs:
            return self.provided_outputs
        return [AgentOutput(query=s.query, output=s.response) for s in self.samples]

    @property
    def outcomes(self) -> list[SessionOutcome]:
        if self.provided_outcomes:
            return self.provided_outcomes
        if self.execution is None:
            return []
        return self.execution.sessions


class MetricBundle(BaseModel):
    """单个计算器的输出。"""

    name: str
    kind: MetricKind
    values: dict[str, float] = Field(default_factory=dict)
    by_category: dict[str, dict[str, float]] = Field(default_factory=dict)
    details: list[dict[str, Any]] = Field(default_factory=list)


class MetricCalculator(ABC):
    """指标计算器协议。每个数据集/指标族实现自己的计算器。"""

    name: ClassVar[str]
    kind: ClassVar[MetricKind]
    metrics: ClassVar[tuple[str, ...] | list[str]] = ()

    def aggregate(self, results: list[BenchmarkResult]) -> BenchmarkResult | None:
        """Optional official aggregation policy; None selects the shared fallback."""
        return None

    @abstractmethod
    def calculate(self, inp: MetricInput) -> MetricBundle:
        """计算指标，返回 bundle。"""
        raise NotImplementedError


class AggregatedMetrics(BaseModel):
    """一次评测的聚合结果。"""

    bundles: list[MetricBundle] = Field(default_factory=list)

    @property
    def flat(self) -> dict[str, float]:
        """扁平化：quality.recall / locomo.f1 / locomo.multi_hop.accuracy。"""
        out: dict[str, float] = {}
        for bundle in self.bundles:
            for key, value in bundle.values.items():
                out[f"{bundle.name}.{key}"] = value
            for category, vals in bundle.by_category.items():
                for key, value in vals.items():
                    out[f"{bundle.name}.{category}.{key}"] = value
        return out

    def bundle(self, name: str) -> MetricBundle | None:
        for item in self.bundles:
            if item.name == name:
                return item
        return None


class MetricsAggregator:
    """统一入口：按序跑计算器，写回横向 metrics 字段（+ 类型化字段）；不处理 benchmark 结果。"""

    def __init__(self, calculators: list[MetricCalculator]):
        self.calculators = calculators

    def run(self, inp: MetricInput) -> MetricReport:
        bundles: list[MetricBundle] = []
        for calculator in self.calculators:
            bundle = calculator.calculate(inp)
            if bundle.kind == "benchmark":
                raise TypeError("Benchmark calculators belong to BenchmarkScorer, not MetricsAggregator")
            bundles.append(bundle)
        aggregated = AggregatedMetrics(bundles=bundles)
        values = {b.kind: b for b in bundles}
        return MetricReport(
            bundles=bundles,
            quality=_quality_result(values.get("quality")),
            utility=_utility_result(values.get("utility")),
            efficiency=_efficiency_result(values.get("efficiency")),
            trace=_trace_result(values.get("trace")),
            flat=aggregated.flat,
        )


def _quality_result(bundle: MetricBundle | None) -> QualityResult | None:
    return _bundle_model(
        bundle,
        QualityResult,
        {"precision": 0.0, "recall": 0.0, "hallucination_rate": 0.0, "omission_rate": 0.0},
    )


def _utility_result(bundle: MetricBundle | None) -> UtilityResult | None:
    return _bundle_model(bundle, UtilityResult, {})


def _efficiency_result(bundle: MetricBundle | None) -> EfficiencyResult | None:
    return _bundle_model(bundle, EfficiencyResult, {})


def _trace_result(bundle: MetricBundle | None) -> TraceResult | None:
    return _bundle_model(bundle, TraceResult, {})


def _bundle_model[TResult: (QualityResult, UtilityResult, EfficiencyResult, TraceResult)](
    bundle: MetricBundle | None, model: type[TResult], defaults: dict[str, float]
) -> TResult | None:
    if bundle is None:
        return None
    data = {**defaults, **bundle.values, "details": bundle.details}
    return model.model_validate(data)


def query_of(item: Any) -> str:
    """从 QA / question 字段取出 query 文本（字符串或 dict）。"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("question") or item.get("query") or "")
    return str(item) if item else ""


def prediction_for_item(outputs: list[AgentOutput], query: str, index: int) -> str:
    """按 query 对齐预测；找不到时再按 round 下标（ingest 之后的评分子 session）。"""
    matches = [item.output for item in outputs if item.query == query]
    if len(matches) == 1:
        return matches[0]
    if 0 <= index < len(outputs):
        return outputs[index].output
    return ""


def outcome_for_round(inp: MetricInput, index: int) -> SessionOutcome | None:
    """Resolve a scored round by session identity, excluding context-only sessions."""
    if inp.task is None:
        return None
    sessions = [session for session in inp.task.sessions if session.query is not None]
    if index >= len(sessions):
        return None
    return next((o for o in inp.outcomes if o.session_id == sessions[index].id), None)


def round_items(inp: MetricInput) -> Iterator[tuple[int, Any, str, Any, str]]:
    """逐回合计算器的公共骨架：按序产出 ``(idx, question_raw, query, gold_raw, pred)``。

    questions/answers 来自 ``task.data``（build_tasks 时写入），按序逐轮对齐；
    pred 走 prediction_for_item（query 精确匹配 → 下标兜底）。
    shopping / search / reasoning / travel 四个计算器的遍历骨架统一走这里，
    各自只保留自己的打分逻辑。
    """
    data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
    questions = data.get("questions") or []
    answers = data.get("answers") or []
    sessions = [session for session in inp.task.sessions if session.query is not None] if inp.task else []
    by_session = {
        sample.session_id: sample.response for sample in inp.samples if sample.session_id is not None
    }
    for idx, question in enumerate(questions):
        query = query_of(question)
        gold = answers[idx] if idx < len(answers) else ""
        if by_session and len(sessions) == len(questions):
            pred = by_session.get(sessions[idx].id, "")
        else:
            pred = prediction_for_item(inp.outputs, query, idx)
        yield idx, question, query, gold, pred


def outputs_from_execution(task: EvalTask | None, execution: TaskExecution) -> list[AgentOutput]:
    """从 TaskExecution.sessions 构造 AgentOutput。

    有 ``SessionOutcome.query`` 时按问题精确匹配；否则按位置对齐
    （session 数必须和 question 数一致才准确）。
    """
    if task is None:
        return []
    data = task.data if isinstance(task.data, dict) else {}
    sessions = execution.sessions

    by_query: dict[str, str] = {}
    for rec in sessions:
        if rec.query:
            by_query[rec.query] = rec.observation or ""
    has_query_mapping = bool(by_query)

    observations = [rec.observation or "" for rec in sessions]
    last = observations[-1] if observations else ""

    qa_items = data.get("qa")
    if isinstance(qa_items, list) and qa_items:
        outputs: list[AgentOutput] = []
        for item in qa_items:
            query = query_of(item)
            if not query:
                continue
            outputs.append(AgentOutput(query=query, output=by_query.get(query, last)))
        return outputs

    questions = data.get("questions") or []
    if not isinstance(questions, list) or not questions:
        return []
    queries = [query_of(item) for item in questions]

    if has_query_mapping:
        return [AgentOutput(query=query, output=by_query.get(query, "")) for query in queries if query]

    scored = observations[-len(queries) :] if len(observations) >= len(queries) else observations
    outputs = []
    for idx, query in enumerate(queries):
        if not query:
            continue
        obs = scored[idx] if idx < len(scored) else last
        outputs.append(AgentOutput(query=query, output=obs))
    return outputs
