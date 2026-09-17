"""评测收尾编排：多 task 指标聚合 + 报告 / summary 落盘。

分工：
- ``metrics_run.py``：per-task 四维 + benchmark、pooled 聚合、run 级扁平指标
- ``summary.py``：summary.md / summary.json 落盘
- 本模块：把上面两步串起来（唯一对外入口 ``finalize_run``）
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..adapters.base import BaseMemoryAdapter
from ..artifacts.provenance import derive_run_id
from ..artifacts.report import ReportGenerator
from ..core.config import ExperimentConfig
from ..evaluation import CalculatorBenchmarkScorer, Verifier
from ..models import (
    BenchmarkResult,
    EvalTask,
    MemoryFact,
    RunProvenance,
    RunSummary,
    SampleResult,
    TaskExecution,
    TaskResult,
    TaskSummary,
    Verdict,
)
from .metrics_run import pool_benchmark, run_metrics
from .run_index import write_run_index
from .summary import write_summary

RuleJudge = Callable[[str, str, str], bool]

__all__ = ["RuleJudge", "finalize_run", "parse_ground_truth"]


def parse_ground_truth(gt: str) -> list[MemoryFact]:
    """解析 memory_ground_truth → MemoryFact 列表。"""
    if not gt:
        return []
    try:
        data = json.loads(gt)
        if isinstance(data, list):
            return [MemoryFact.model_validate(d) for d in data]
    except json.JSONDecodeError:
        pass
    return [MemoryFact(fact=line.strip()) for line in gt.splitlines() if line.strip()]


def finalize_run(
    cfg: ExperimentConfig,
    tasks: list[EvalTask],
    results: list[TaskExecution],
    adapters: dict[str, BaseMemoryAdapter],
    output_dir: str | Path,
    n_concurrent: int = 1,
    mock: bool = False,
    rule_judge: RuleJudge | None = None,
    provenance: RunProvenance | None = None,
) -> RunSummary:
    """跑完整指标管线并生成报告（per-task 报告 + 整批汇总）。"""
    summary = RunSummary(n_tasks=len(results), n_concurrent=n_concurrent, mock=mock)
    bench_results: list[BenchmarkResult] = []
    task_results: list[TaskResult] = []

    judge_cfg: dict[str, Any] = cfg.judging.model_dump()
    if mock:
        judge_cfg["type"] = "rule"

    for task, result in zip(tasks, results, strict=True):
        ground_truth = parse_ground_truth(task.memory_ground_truth)

        bench_name = _benchmark_name(task)
        scorer = (
            CalculatorBenchmarkScorer(
                bench_name,
                judge=rule_judge if mock else None,
                llm_config=judge_cfg,
                **_benchmark_options(task),
            )
            if bench_name
            else None
        )
        from ..evaluation import Evaluator
        from ..metrics import EfficiencyCalculator, QualityCalculator, TraceCalculator, UtilityCalculator

        calculators = [UtilityCalculator(), EfficiencyCalculator(), TraceCalculator()]
        if ground_truth:
            calculators.insert(0, QualityCalculator(judge_cfg))
        verifier: Verifier | None = None
        if mock and rule_judge is not None:
            answers = task.data.get("answers", []) if isinstance(task.data, dict) else []

            def _verify(sample: SampleResult, answers: list[Any] = answers) -> Verdict:
                gold = sample.ground_truth or (str(answers[0]) if answers else "")
                passed = bool(rule_judge(sample.response, gold, sample.query))
                return Verdict(label="correct" if passed else "incorrect", score=1.0 if passed else 0.0)

            verifier = _verify

        evaluator = Evaluator(verifier, scorer, calculators)
        adapter = adapters.get(task.name)
        memory_files = _memory_files(adapter)
        task_result = evaluator.evaluate(
            task, result, memory_files=memory_files, ground_truth_facts=ground_truth
        )
        task_results.append(task_result)
        benchmark_result = task_result.benchmark
        bench_main = benchmark_result.primary_score if benchmark_result else None
        if benchmark_result:
            bench_results.append(benchmark_result)

        summary.per_task.append(
            TaskSummary(
                task_name=task.name,
                n_sessions=len(result.sessions),
                n_success=sum(1 for rec in result.sessions if rec.success),
                report_dir=str(
                    ReportGenerator(output_dir).generate(
                        task_result, config=cfg, provenance=provenance, formats=cfg.output.format
                    )
                ),
                benchmark_f1=bench_main,
            )
        )

    _apply_averages(summary, task_results)
    if bench_results:
        summary.benchmark = pool_benchmark(bench_results, summary.warnings)
    summary.metrics = run_metrics(summary, task_results)
    summary.experiment_name = cfg.experiment.name
    summary.run_id = derive_run_id(cfg)
    summary.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_summary(summary, output_dir, provenance=provenance, formats=cfg.output.format)
    # 结果索引：分析方取数地图（summary/tasks/sessions→trial→trajectory 的完整清单）
    write_run_index(
        output_dir,
        run_id=summary.run_id,
        experiment_name=summary.experiment_name,
        generated_at=summary.generated_at,
        tasks=tasks,
        results=task_results,
    )
    return summary


def _memory_files(adapter: BaseMemoryAdapter | None) -> dict[str, str]:
    if adapter is None:
        return {}
    files = adapter.read_memory_files()
    return files if isinstance(files, dict) else {}


def _benchmark_options(task: EvalTask) -> dict[str, str]:
    data = task.data if isinstance(task.data, dict) else {}
    mode = str(data.get("judgement_mode") or "hint")
    lang = str(data.get("language") or "zh")
    return {"judgement_mode": mode, "lang": lang}


def _benchmark_name(task: EvalTask) -> str | None:
    if task.benchmark:
        return str(task.benchmark)
    if isinstance(task.data, dict) and task.data.get("benchmark"):
        return str(task.data["benchmark"])
    return None


def _apply_averages(summary: RunSummary, results: list[TaskResult]) -> None:
    """整批平均（quality 只对配了 ground truth 的 task 平均）。

    是否「计算过」以 ground truth 判定（QualityResult 默认 0.0 与算得 0 无法区分）。
    """
    n = len(results)
    if not n:
        return
    quality = [r.metrics.quality for r in results if r.metrics is not None and r.metrics.quality is not None]
    if quality:
        summary.quality_recall_avg = sum(item.recall for item in quality) / len(quality)
        summary.quality_precision_avg = sum(item.precision for item in quality) / len(quality)
    utility = [r.metrics.utility for r in results if r.metrics is not None and r.metrics.utility is not None]
    summary.utility_success_rate_avg = sum(item.success_rate for item in utility) / n if utility else 0.0
