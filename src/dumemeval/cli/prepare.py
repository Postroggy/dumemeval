"""``dumemeval prepare``：一键准备官方评测数据到本地缓存。

下载完整官方数据集（不随仓库分发：体积 + 上游许可）并切出 smoke 子集。
smoke 子集本身随仓库捆绑在 ``data/smoke/``（零下载），本命令给需要
完整数据的真跑（configs/backends/）与重新生成捆绑子集用。

用法：
    dumemeval prepare                  # 注册表里所有可下载数据集
    dumemeval prepare --dataset locomo
    dumemeval prepare --dataset shopping --force   # 强制重新下载
    dumemeval prepare --root /path     # 覆盖缓存根（默认 ~/.cache/dumemeval/datasets）
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..datasets import prepare as prep


def cmd_prepare(args: argparse.Namespace) -> int:
    if getattr(args, "environment_config", None):
        from ..config import load_config
        from ..task_environments.prepare import prepare_environment

        cfg = load_config(args.environment_config)
        report = prepare_environment(cfg, clone=args.clone_reference)
        print(report.model_dump_json(indent=2))
        return 0 if report.ready else 1
    root = Path(args.root).expanduser() if args.root else None
    datasets = tuple(prep.downloadable_names()) if args.dataset == "all" else (args.dataset,)

    print(f"📦 缓存根: {root or prep.cache_root()}\n")
    for name in datasets:
        try:
            paths = prep.prepare_dataset(name, root=root, force=args.force)
        except (OSError, ValueError) as exc:
            print(f"❌ {name}: 下载/写入失败（网络或磁盘）: {exc}")
            return 1

        smoke = paths.get("smoke")
        print(f"  ✓ {name}:")
        print(f"      full  → {paths['full']}")
        if smoke is not None and smoke.exists():
            print(f"      smoke → {smoke}")
        spec = prep.DATASET_REGISTRY.get(prep.canonical_dataset_name(name))
        if spec is not None and spec.prepare_note:
            # shopping 任务文件 ≠ webshop 商品库；官方 ASIN 分依赖 env server。
            print("      ⚠️  " + spec.prepare_note.replace("\n", "\n        "))

    print(
        "\n下一步：\n"
        "  make smoke-mock         # 编排验证（零 Docker / 零密钥）\n"
        "  make smoke              # Harbor 真跑对照（需 Docker + ANTHROPIC_*）\n"
        "  也可设置 DUMEMEVAL_DATA_DIR 指向已有数据目录，跳过下载。"
    )
    return 0
