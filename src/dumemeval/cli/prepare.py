"""``dumemeval prepare``：一键准备官方评测数据到本地缓存。

下载完整官方数据集（不随仓库分发：体积 + 上游许可）并切出 smoke 子集。
smoke 子集本身随仓库捆绑在 ``data/smoke/``（零下载），本命令给需要
完整数据的真跑（configs/backends/）与重新生成捆绑子集用。

用法：
    dumemeval prepare                  # locomo + shopping
    dumemeval prepare --dataset locomo
    dumemeval prepare --dataset shopping --force   # 强制重新下载
    dumemeval prepare --root /path     # 覆盖缓存根（默认 ~/.cache/dumemeval/datasets）
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..datasets import prepare as prep


def cmd_prepare(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser() if args.root else None
    datasets = tuple(prep.dataset_names()) if args.dataset == "all" else (args.dataset,)

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
        if name in ("shopping", "bundled_shopping"):
            print(
                "      ⚠️  这只是任务文件（目标 ASIN）。官方 webshop 商品库与 env server\n"
                "        需另按 MemoryArena setup_web_shopping.md 启动（默认 :8005），\n"
                "        否则 shopping 官方 ASIN 分恒为 0——这是环境缺口，不是模型分数。"
            )

    print(
        "\n下一步：\n"
        "  make smoke-mock         # 编排验证（零 Docker / 零密钥）\n"
        "  make smoke              # Harbor 真跑对照（需 Docker + ANTHROPIC_*）\n"
        "  也可设置 DUMEMEVAL_DATA_DIR 指向已有数据目录，跳过下载。"
    )
    return 0
