"""CLI 参数解析与子命令分发。

子命令实现分别在 run.py / inspect.py / compare.py / prepare.py；本模块只做 parser 组装。
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    """组装 argparse parser（与执行逻辑分离，便于测试）。"""
    parser = argparse.ArgumentParser(
        prog="dumemeval", description="DuMemEval: Agent-first memory evaluation framework"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="运行一次评测")
    run_parser.add_argument("--config", required=True, help="评测配置（yaml/json）")
    run_parser.add_argument("--backend", help="覆盖 memory 后端（--backend mem0 等）")
    run_parser.add_argument("--mock", action="store_true", help="用 MockRunner 模拟执行（验证编排）")
    run_parser.add_argument(
        "--n-concurrent",
        type=int,
        default=None,
        help="跨 task 并行度（默认取 execution.n_concurrent；task 内 session 因 memory 依赖恒串行）",
    )
    run_parser.add_argument(
        "--no-resume",
        action="store_true",
        help="忽略 checkpoints，强制重跑所有 task（默认跳过已完成 task）",
    )
    run_parser.add_argument(
        "--num-runs",
        type=int,
        default=None,
        help="LLM-as-Judge 重复次数（覆盖 judging.num_runs）",
    )
    run_parser.add_argument(
        "--skip-failed-judge",
        action="store_true",
        help="judge 失败记 SKIPPED 而非中断（覆盖 judging.skip_failed）",
    )
    run_parser.add_argument(
        "--save-model-input",
        action="store_true",
        help="把 judge user prompt 写入 Verdict.model_input（覆盖 judging.save_model_input）",
    )
    run_parser.add_argument(
        "--output",
        default=None,
        help="输出目录（默认用配置 output.dir，未写则 results）",
    )

    list_parser = sub.add_parser("list", help="列出已注册的 adapter / protocol / benchmark")
    list_parser.add_argument(
        "--kind",
        choices=("adapters", "benchmarks", "protocols", "all"),
        default="all",
    )

    prepare_parser = sub.add_parser("prepare", help="一键下载官方评测数据到本地缓存并切 smoke 子集")
    prepare_parser.add_argument(
        "--dataset",
        choices=None,
        default="all",
        help="要准备的数据集（默认 all）",
    )
    prepare_parser.add_argument("--force", action="store_true", help="强制重新下载（否则缓存命中即跳过）")
    prepare_parser.add_argument(
        "--root", default=None, help="覆盖缓存根目录（默认 ~/.cache/dumemeval/datasets）"
    )

    cmp_parser = sub.add_parser(
        "compare",
        help="比较多个 run（有 --baseline 出 Δ；无 baseline 出横评排名）",
    )
    cmp_parser.add_argument("runs", nargs="+", help="run 目录（各含 summary.json）")
    cmp_parser.add_argument(
        "--baseline",
        default=None,
        help="基线 run 的 label（默认目录名）；不给则只排名",
    )
    cmp_parser.add_argument("--output", default=None, help="落盘 comparison.md/json 的目录")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "run":
        from .run import cmd_run

        return cmd_run(args)
    if args.command == "list":
        from .inspect import cmd_list

        return cmd_list(args.kind)
    if args.command == "prepare":
        from .prepare import cmd_prepare

        return cmd_prepare(args)
    if args.command == "compare":
        from .compare import cmd_compare

        return cmd_compare(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
