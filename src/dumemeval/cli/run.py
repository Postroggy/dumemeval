"""``dumemeval run``：一次评测的完整执行。"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any

from ..config.loader import load_config
from ..core.config import ExperimentConfig
from ..execution.executor import SessionExecutor
from ..models import MemorySpec, RunSummary


def cmd_run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg: ExperimentConfig = load_config(args.config)
    _apply_hermes_anthropic_env(cfg)
    _apply_overrides(cfg, args)
    _preflight(cfg, args)

    tasks = _build_tasks(cfg)
    if not tasks:
        return 1

    results, adapters = _run_tasks(cfg, tasks, args)
    _finalize(cfg, tasks, results, adapters, args)
    return 0


def _preflight(cfg: ExperimentConfig, args: argparse.Namespace) -> None:
    """在创建 Harbor 容器前检查本轮实验所需的外部凭据。"""
    if args.mock or cfg.execution.engine == "mock":
        return
    if cfg.judging.type == "llm_judge":
        env_name = cfg.judging.api_key_env
        if not os.environ.get(env_name):
            raise ValueError(
                f"Preflight failed: missing judge credential {env_name}. "
                "Configure judging.api_key_env or export it before starting Harbor."
            )
        if not cfg.judging.model:
            raise ValueError("Preflight failed: judging.model is required for llm_judge")
        if not cfg.judging.base_url:
            raise ValueError("Preflight failed: judging.base_url is required for llm_judge")


# ── 执行与收尾 ───────────────────────────────────────────────────────────────


def _run_tasks(
    cfg: ExperimentConfig,
    tasks: list[Any],
    args: argparse.Namespace,
) -> tuple[list[Any], dict[str, Any]]:
    """并行执行所有 task，返回 (results, per-task adapters)。

    task 间并行、task 内 session 串行；adapters 是 runner 实际创建并 setup 过的
    实例，finalize 读 memory_files 用它们。
    """
    import asyncio

    from ..adapters.base import BaseMemoryAdapter
    from ..adapters.registry import create_adapter
    from ..lifecycle.parallel import ParallelTaskRunner

    n_concurrent = max(1, min(args.n_concurrent or cfg.execution.n_concurrent, len(tasks)))
    output_dir = args.output or cfg.output.dir
    resume = cfg.execution.resume and not args.no_resume
    if len(tasks) > 1:
        print(f"   ⚡ 跨 task 并行: {n_concurrent}/{len(tasks)}（task 内 session 串行：memory 依赖）")
    if resume:
        print("   ⏭  resume: 跳过 output/checkpoints 里已完成的 task（--no-resume 关闭）")

    def _adapter_factory(task_name: str) -> BaseMemoryAdapter:
        # 多 task 时 memory 目录按 task 分子目录（并行隔离；单 task 保持原路径）
        spec = _to_memory_spec(cfg, task_suffix=task_name if len(tasks) > 1 else None)
        return create_adapter(spec)

    parallel = ParallelTaskRunner(
        adapter_factory=_adapter_factory,
        executor=build_executor(cfg, mock=args.mock, output_dir=output_dir),
        protocol=cfg.protocol_instance,
        output_dir=output_dir,
        n_concurrent=n_concurrent,
        resume=resume,
    )
    results = asyncio.run(parallel.run(tasks))
    return results, parallel.adapters


def _finalize(
    cfg: ExperimentConfig,
    tasks: list[Any],
    results: list[Any],
    adapters: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    """指标聚合 + 报告落盘 + 终端摘要。"""
    from ..artifacts.provenance import snapshot_run
    from ..pipeline import finalize_run

    n_concurrent = max(1, min(args.n_concurrent or cfg.execution.n_concurrent, len(tasks)))
    output_dir = args.output or cfg.output.dir
    used_mock = args.mock or cfg.execution.engine == "mock"
    provenance = snapshot_run(
        cfg,
        output_dir=output_dir,
        config_path=args.config,
        mock=used_mock,
        n_concurrent=n_concurrent,
    )
    summary = finalize_run(
        cfg,
        tasks,
        results,
        adapters=adapters,
        output_dir=output_dir,
        n_concurrent=n_concurrent,
        mock=used_mock,
        rule_judge=rule_qa_judge if used_mock else None,
        provenance=provenance,
    )
    _print_summary(summary, results, used_mock=used_mock)


# ── 配置覆盖与任务构建 ──────────────────────────────────────────────────────


def _apply_hermes_anthropic_env(cfg: ExperimentConfig) -> None:
    """Hermes agent 走 Anthropic 协议时补齐 env（绕开网关的 OpenAI tools 校验）。"""
    if cfg.agent.runtime != "hermes" or not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return
    os.environ.setdefault("ANTHROPIC_API_KEY", os.environ["ANTHROPIC_AUTH_TOKEN"])
    if os.environ.get("ANTHROPIC_BASE_URL"):
        os.environ.setdefault("ANTHROPIC_BASE_URL", os.environ["ANTHROPIC_BASE_URL"].rstrip("/") + "/v1")


def _apply_overrides(cfg: ExperimentConfig, args: argparse.Namespace) -> None:
    """CLI 参数覆盖配置（优先级：CLI > yaml）。"""
    if args.backend:
        cfg.memory.name = args.backend
    if args.num_runs is not None:
        cfg.judging.num_runs = args.num_runs
    if args.skip_failed_judge:
        cfg.judging.skip_failed = True
    if args.save_model_input:
        cfg.judging.save_model_input = True


def _build_tasks(cfg: ExperimentConfig) -> list[Any]:
    """配置占位 sessions；声明 benchmark 时由适配器 build_tasks 覆盖。"""
    if not (cfg.task.benchmark and cfg.task.data is not None):
        return [cfg.to_eval_task()]

    from ..datasets import get_benchmark
    from ..datasets.loader import DatasetFactory

    dataset = DatasetFactory.create(cfg.task.data.model_dump()).load()
    print(f"   📦 数据源: {dataset}")
    adapter = get_benchmark(cfg.task.benchmark)
    built = adapter.build_tasks(
        adapter.data_type.from_raw(dataset.data), **(cfg.task.benchmark_options or {})
    )
    if not built:
        print(f"❌ benchmark {cfg.task.benchmark} 未从数据构建出任何任务")
        return []
    # 配置级字段回填：适配器按数据集口径构建任务，不知道评测设计层的选择
    # （memory_instruction / task_environment 是实验变量，归配置所有；其余字段
    #   如 memory_ground_truth 已由适配器按官方口径填好，不覆盖）
    task_environment = cfg.task.task_environment.model_dump() if cfg.task.task_environment else {}
    protocol = cfg.protocol_instance
    for task in built:
        task.memory_instruction = cfg.task.memory_instruction
        if task_environment:
            merged = dict(task.task_environment or {})
            merged.update({k: v for k, v in task_environment.items() if v is not None})
            if isinstance(task_environment.get("config"), dict) or isinstance(merged.get("config"), dict):
                cfg_config = dict(merged.get("config") or {})
                cfg_config.update(dict(task_environment.get("config") or {}))
                merged["config"] = cfg_config
            task.task_environment = merged
        if cfg.task.judgement_mode:
            if not isinstance(task.data, dict):
                task.data = {}
            # 配置层是实验变量，覆盖适配器默认（与 memory_instruction 回填同语义）
            task.data["judgement_mode"] = cfg.task.judgement_mode
        # 协议归一化 + 逐任务校验（协议可能强制 session 属性，如 test_only 全关注入；
        # 此前只校验 built[0]，后续 task 漏查）
        protocol.normalize_sessions(task.sessions)
        protocol.validate(
            n_sessions=len(task.sessions),
            memory_injects=[s.memory_inject for s in task.sessions],
        )
    print(f"   🎯 benchmark 任务: {len(built)} 个样本（{built[0].name} … {built[-1].name}）")
    return built


def _to_memory_spec(cfg: ExperimentConfig, task_suffix: str | None = None) -> MemorySpec:
    """ExperimentConfig.memory → MemorySpec（adapters 用）。"""
    path = cfg.memory.path
    if task_suffix and path:
        path = f"{path.rstrip('/')}/{task_suffix}"
    return MemorySpec(
        name=cfg.memory.name,
        type=cfg.memory.type,
        path=path,
        base_url=cfg.memory.base_url,
        user_id=cfg.memory.user_id,
        team_id=cfg.memory.team_id,
        agent_id=cfg.memory.agent_id,
        config=cfg.memory.config,
    )


# ── 执行器 ──────────────────────────────────────────────────────────────────


def build_executor(cfg: ExperimentConfig, *, mock: bool, output_dir: str) -> SessionExecutor:
    """构建执行器（--mock 优先，其次 execution.engine；Harbor 缺失时回退 mock）。"""
    if mock or cfg.execution.engine == "mock":
        from ..execution.mock import MockRunner

        return MockRunner()

    if not harbor_available():
        print("⚠️  Harbor 未安装，回退到 MockRunner。安装: uv sync --extra harbor")
        from ..execution.mock import MockRunner

        return MockRunner()

    from ..execution.harbor_bridge import HarborBridge
    from ..execution.task_dir import TaskDirGenerator
    from ..execution.trial_config import (
        HarborAgentConfig,
        HarborConfig,
        HarborEnvironmentConfig,
        MountConfig,
    )

    env_spec = cfg.execution.environment
    return HarborBridge(
        config=HarborConfig(
            trials_dir=str(Path(output_dir) / "trials"),
            agent=HarborAgentConfig(
                name=cfg.agent.runtime,
                model=cfg.agent.model,
                setup_timeout_sec=cfg.agent.setup_timeout_sec,
                temperature=cfg.agent.temperature,
                max_tokens=cfg.agent.max_tokens,
                skills_dir=str(Path(cfg.agent.skills_dir).expanduser().resolve())
                if cfg.agent.skills_dir
                else None,
            ),
            environment=HarborEnvironmentConfig(
                type=env_spec.type,
                force_build=env_spec.force_build,
                docker_image=env_spec.docker_image,
                env=env_spec.env,
                mounts=[MountConfig.model_validate(m.model_dump()) for m in env_spec.mounts],
            ),
        ),
        task_dir_generator=TaskDirGenerator(tasks_root=cfg.output.tasks_dir, env_spec=env_spec),
    )


def harbor_available() -> bool:
    """探测 Harbor 是否可用（深度 import 检查）。"""
    try:
        import harbor  # noqa: F401
        from harbor.models.trial.config import TrialConfig  # noqa: F401
        from harbor.trial.trial import Trial  # noqa: F401

        return True
    except ImportError:
        return False


def rule_qa_judge(pred: str, gold: str, question: str) -> bool:
    """mock / 无 LLM 时的规则 accuracy：子串互含。"""
    if not pred or not gold:
        return False
    p, g = pred.lower(), gold.lower()
    return g in p or p in g


# ── 终端摘要 ────────────────────────────────────────────────────────────────


def _print_summary(summary: RunSummary, results: list[Any], *, used_mock: bool) -> None:
    print(f"\n✅ 评测完成: {summary.n_tasks} 个 task / memory={results[0].memory_backend}")
    for task in summary.per_task:
        ok = task.n_success == task.n_sessions and task.n_sessions > 0
        mark = "🟢" if ok else "🔴"
        print(
            f"   {mark} {task.task_name}: {task.n_success}/{task.n_sessions} session 成功 → {task.report_dir}"
        )

    if used_mock:
        print("   ⚠️  mock 模式：observation 是占位文本（无真实 agent 输出），")
        print("      指标仅用于验证编排链路，不代表 agent 真实水平。")
    elif results and all(
        not str(rec.get("observation") or "").strip()
        for r in results
        for rec in getattr(r, "session_outcomes", [o.model_dump() for o in getattr(r, "sessions", [])])
    ):
        print("   ⚠️  所有 session 的 agent 输出为空（未采集到 trajectory.json），")
        print("      依赖输出的 benchmark 指标会算 0 分，请检查 agent 是否正常运行。")

    for warning in summary.warnings:
        print(f"   ⚠️  {warning}")
    if summary.quality_recall_avg is not None:
        print(
            f"   Quality(avg): recall={summary.quality_recall_avg:.3f} "
            f"precision={summary.quality_precision_avg:.3f}"
        )
    print(f"   Utility(avg): success_rate={summary.utility_success_rate_avg:.3f}")
    if summary.benchmark is not None:
        shown = " ".join(f"{k}={v:.3f}" for k, v in list(summary.benchmark.values.items())[:6])
        print(f"   Benchmark[{summary.benchmark.benchmark}] (pooled): {shown}")
