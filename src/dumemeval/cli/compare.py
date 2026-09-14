"""``dumemeval compare``：跨 run 比较（接 memory vs 不接 / 多 backend 横评）。"""

from __future__ import annotations

import argparse

from ..comparison.report import render_markdown, write_comparison
from ..comparison.service import compare_runs, load_run


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        runs = [load_run(path) for path in args.runs]
        comparison = compare_runs(runs, baseline=args.baseline)
    except (FileNotFoundError, ValueError) as exc:
        # 用户输入问题（目录缺 summary.json / label 重复 / baseline 不存在）：
        # 打清晰错误，不甩 traceback
        print(f"❌ {exc}")
        return 2

    print(render_markdown(comparison, runs))
    if args.output:
        out = write_comparison(comparison, runs, args.output)
        print(f"→ {out / 'comparison.md'}")
    return 0
