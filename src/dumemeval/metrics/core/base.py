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
    EfficiencyResult,
    EvalResult,
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

    model_config = {"arbitrary_types_allowed": True}

    task: EvalTask
    execution: TaskExecution
    samples: list[SampleResult] = Field(default_factory=list)
    benchmark: Any | None = None
    memory_files: dict[str, str] = Field(default_factory=dict)
    ground_truth_facts: list[MemoryFact] = Field(default_factory=list)
    probe_events: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def outputs(self) -> list[AgentOutput]:
        return [AgentOutput(query=s.query, output=s.response) for s in self.samples]

    @property
    def outcomes(self) -> list[SessionOutcome]:
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

    @abstractmethod
    def calculate(self, inp: MetricInput) -> MetricBundle:
        """计算指标，必要时回写 inp.result 的类型化字段。"""
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
    """统一入口：按序跑计算器，写回横向 metrics 字段（+ 类型化字段）；不处理 benchmark 结果。。"""

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
            quality=_quality_result(values.get("quality")),
            utility=_utility_result(values.get("utility")),
            efficiency=_efficiency_result(values.get("efficiency")),
            trace=_trace_result(values.get("trace")),
            flat=aggregated.flat,
        )


def _quality_result(b):
    return _bundle_model(
        b, QualityResult, {"precision": 0.0, "recall": 0.0, "hallucination_rate": 0.0, "omission_rate": 0.0}
    )


def _utility_result(b):
    return _bundle_model(b, UtilityResult, {})


def _efficiency_result(b):
    return _bundle_model(b, EfficiencyResult, {})


def _trace_result(b):
    return _bundle_model(b, TraceResult, {})


def _bundle_model(bundle, model, defaults):
    if bundle is None:
        return None
    data = {**defaults, **bundle.values, "details": bundle.details}
    return model.model_validate(data)


def session_records_to_outcomes(records: list[dict[str, Any]]) -> list[SessionOutcome]:
    """EvalResult.session_outcomes（dict）→ SessionOutcome。"""
    return [
        SessionOutcome(
            session_id=int(rec.get("session_id", 1)),
            success=bool(rec.get("success", False)),
            observation=str(rec.get("observation", "")),
            error=rec.get("error"),
            tokens_in=int(rec.get("tokens_in", 0) or 0),
            tokens_out=int(rec.get("tokens_out", 0) or 0),
        )
        for rec in records
    ]


def query_of(item: Any) -> str:
    """从 QA / question 字段取出 query 文本（字符串或 dict）。"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("question") or item.get("query") or "")
    return str(item) if item else ""


def prediction_for_item(outputs: list[AgentOutput], query: str, index: int) -> str:
    """按 query 对齐预测；找不到时再按 round 下标（ingest 之后的评分子 session）。"""
    by_query = {item.query: item.output for item in outputs}
    if query in by_query:
        return by_query[query]
    if 0 <= index < len(outputs):
        return outputs[index].output
    return ""


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
    for idx, question in enumerate(questions):
        query = query_of(question)
        gold = answers[idx] if idx < len(answers) else ""
        pred = prediction_for_item(inp.outputs, query, idx)
        yield idx, question, query, gold, pred


def outputs_from_result(task: EvalTask | None, result: EvalResult) -> list[AgentOutput]:
    """从 session observation 构造 AgentOutput。

    优先路径（精确）：``session_outcomes[].query`` 由 SessionRunner 从
    ``SessionSpec.query`` 回填——只要 build_tasks 显式设置了该字段，就按
    query 精确匹配 observation，不依赖 session 在序列里的位置。

    兼容路径（近似，仅当 outcomes 完全没有 query 时触发）：假设 sessions
    尾部恰好是"每个 question 一个 session"，按位置切片对齐。这对 travel
    这类"session 数 != question 数"（有 memory 注入轮）的任务不成立，
    只在旧任务/未设置 query 时兜底，并在结果里打上 "approximate" 标记。
    """
    if task is None:
        return []
    data = task.data if isinstance(task.data, dict) else {}
    outcomes = result.session_outcomes

    by_query: dict[str, str] = {}
    for rec in outcomes:
        query = rec.get("query")
        if query:
            by_query[str(query)] = str(rec.get("observation") or "")
    has_query_mapping = bool(by_query)

    observations = [str(rec.get("observation") or "") for rec in outcomes]
    last = observations[-1] if observations else ""

    qa_items = data.get("qa")
    if isinstance(qa_items, list) and qa_items:
        outputs: list[AgentOutput] = []
        for item in qa_items:
            query = query_of(item)
            if not query:
                continue
            # qa 类任务（LoCoMo）：全部问题共用同一个问答回合 session，
            # 该 session 通常没有单独的 query（它回答的是全部问题），
            # 故此处保留"取最后一次 observation"的语义，与 has_query_mapping 无关。
            outputs.append(AgentOutput(query=query, output=by_query.get(query, last)))
        return outputs

    questions = data.get("questions") or []
    if not isinstance(questions, list) or not questions:
        return []
    queries = [query_of(item) for item in questions]

    if has_query_mapping:
        return [AgentOutput(query=query, output=by_query.get(query, "")) for query in queries if query]

    # 兼容路径：无 query 映射时按位置切片（仅当 session 数 == question 数才准确）。
    scored = observations[-len(queries) :] if len(observations) >= len(queries) else observations
    outputs = []
    for idx, query in enumerate(queries):
        if not query:
            continue
        obs = scored[idx] if idx < len(scored) else last
        outputs.append(AgentOutput(query=query, output=obs))
    return outputs
