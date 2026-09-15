"""准备官方评测数据到本地缓存，供完整数据真跑（configs/backends/）使用。

smoke 子集已随仓库捆绑在 ``data/smoke/``（零下载），本模块负责下载**完整**
官方数据（不随仓库分发：体积 + 上游许可）并重新切出 smoke 子集，供
``dumemeval prepare`` 调用。完整数据缓存到 ``~/.cache/dumemeval/datasets``
（可用 ``DUMEMEVAL_DATA_DIR`` 覆盖）。
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class DatasetSpec(BaseModel):
    """可准备数据集的声明：来源、缓存格式和可选 smoke 转换。"""

    name: str
    source: str | None = None
    bundled: str | None = None
    cache: str
    format: Literal["json", "jsonl"]
    smoke: str | None = None
    prepare_note: str | None = None


DEFAULT_CACHE = Path.home() / ".cache" / "dumemeval" / "datasets"


# ── 逻辑数据名注册表 ──────────────────────────────────────────────────────────
# 用户写 ``data.name`` 即可，框架负责找文件（解析顺序：仓库捆绑 → prepare 缓存）。
# bundled: 相对仓库根（dumeval/）的捆绑子集路径；cache: 相对缓存根（cache_root()）。
DATASET_REGISTRY: dict[str, DatasetSpec] = {
    "locomo_smoke": DatasetSpec(
        name="locomo_smoke",
        bundled="data/smoke/locomo_smoke.json",
        cache="locomo/locomo_smoke.json",
        format="json",
        smoke=None,
    ),
    "locomo": DatasetSpec(
        name="locomo",
        source="https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json",
        cache="locomo/locomo10.json",
        format="json",
        smoke="locomo",
    ),
    "shopping_smoke": DatasetSpec(
        name="shopping_smoke",
        bundled="data/smoke/shopping_smoke.jsonl",
        cache="memoryarena/bundled_shopping_smoke.jsonl",
        format="jsonl",
        smoke=None,
    ),
    "bundled_shopping": DatasetSpec(
        name="bundled_shopping",
        source="https://huggingface.co/datasets/ZexueHe/memoryarena/resolve/main/bundled_shopping/data.jsonl",
        cache="memoryarena/bundled_shopping.jsonl",
        format="jsonl",
        smoke="shopping",
        prepare_note=(
            "这只是任务文件（目标 ASIN）。官方 webshop 商品库与 env server\n"
            "需另按 MemoryArena setup_web_shopping.md 启动（默认 :8005），\n"
            "没有真实购买证据时，Shopping 官方分数保持未测。"
        ),
    ),
}

# CLI / 配置别名：用户写 shopping，注册表键是 bundled_shopping。
PREPARE_ALIASES: dict[str, str] = {"shopping": "bundled_shopping"}


def dataset_names() -> list[str]:
    """已注册的逻辑数据名。"""
    return sorted(DATASET_REGISTRY)


def downloadable_names() -> list[str]:
    """``dumemeval prepare`` 能下载的数据集（注册表里有 source）。"""
    return sorted(name for name, spec in DATASET_REGISTRY.items() if spec.source)


def prepare_cli_names() -> list[str]:
    """prepare 子命令接受的名字：可下载项 + 别名。"""
    return sorted({*downloadable_names(), *PREPARE_ALIASES})


def canonical_dataset_name(name: str) -> str:
    return PREPARE_ALIASES.get(name, name)


def resolve_dataset(name: str, root: Path | None = None) -> Path | None:
    """按逻辑数据名解析实际文件路径。

    解析顺序：仓库捆绑 ``data/smoke/`` → prepare 缓存（``root`` 或
    ``cache_root()``）。未命中返回 None（调用方报错给下一步提示）。
    """
    entry = DATASET_REGISTRY.get(name)
    if entry is None:
        return None
    bundled_rel = entry.bundled
    if bundled_rel:
        repo_path = Path(__file__).resolve().parents[3] / bundled_rel
        if repo_path.exists():
            return repo_path
    cache_rel = entry.cache
    if cache_rel:
        cached = (root or cache_root()) / cache_rel
        if cached.exists():
            return cached
    return None


def cache_root() -> Path:
    override = os.environ.get("DUMEMEVAL_DATA_DIR")
    return Path(override).expanduser() if override else DEFAULT_CACHE


def locomo_full_path(root: Path | None = None) -> Path:
    return (root or cache_root()) / "locomo" / "locomo10.json"


def locomo_smoke_path(root: Path | None = None) -> Path:
    return (root or cache_root()) / "locomo" / "locomo_smoke.json"


def shopping_full_path(root: Path | None = None) -> Path:
    return (root or cache_root()) / "memoryarena" / "bundled_shopping.jsonl"


def shopping_smoke_path(root: Path | None = None) -> Path:
    return (root or cache_root()) / "memoryarena" / "bundled_shopping_smoke.jsonl"


def _download(url: str, dest: Path, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "dumemeval-prepare"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)


def _evidence_sessions(qa: dict[str, Any]) -> set[int]:
    found: set[int] = set()
    for item in qa.get("evidence") or []:
        for part in str(item).split(";"):
            match = re.match(r"^D(\d+):", part.strip())
            if match:
                found.add(int(match.group(1)))
    return found


def slice_locomo_smoke(raw: list[Any], *, n_sessions: int = 4, per_category: int = 1) -> list[dict[str, Any]]:
    """从官方 locomo10 切出有记忆语义的 smoke：对话 0 的前 N 个 session + 每类 1 题。"""
    if not raw:
        raise ValueError("empty locomo payload")
    conv_item = raw[0]
    conversation = dict(conv_item.get("conversation") or {})
    kept_keys: dict[str, Any] = {}
    for key, value in conversation.items():
        match = re.match(r"^session_(\d+)$", key) or re.match(r"^session_(\d+)_date_time$", key)
        if match and int(match.group(1)) <= n_sessions:
            kept_keys[key] = value
    by_cat: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for qa in conv_item.get("qa") or []:
        sessions = _evidence_sessions(qa)
        if sessions and sessions <= set(range(1, n_sessions + 1)):
            by_cat[int(qa.get("category") or 0)].append(qa)
    selected: list[dict[str, Any]] = []
    for cat in sorted(by_cat):
        selected.extend(by_cat[cat][:per_category])
    return [
        {
            "sample_id": conv_item.get("sample_id"),
            "conversation": kept_keys,
            "qa": selected,
            "event_summary": conv_item.get("event_summary"),
            "observation": conv_item.get("observation"),
            "session_summary": conv_item.get("session_summary"),
        }
    ]


def slice_shopping_smoke(rows: list[Any], *, n_rounds: int = 2) -> list[dict[str, Any]]:
    """取第 0 个样本的前 N 回合（跨回合兼容约束从第 2 回合开始）。"""
    if not rows:
        raise ValueError("empty shopping payload")
    row = dict(rows[0])
    questions = list(row.get("questions") or [])[:n_rounds]
    answers = list(row.get("answers") or [])[:n_rounds]
    row["questions"] = questions
    row["answers"] = answers
    return [row]


def prepare_dataset(name: str, *, root: Path | None = None, force: bool = False) -> dict[str, Path]:
    """按注册的 DatasetSpec 准备数据；没有 smoke 转换时只返回 full。"""
    key = canonical_dataset_name(name)
    spec = DATASET_REGISTRY.get(key)
    if spec is None:
        raise ValueError(f"Unknown dataset: {name!r}. Supported: {dataset_names()}")
    root = root or cache_root()
    full = root / spec.cache
    if force or not full.exists():
        if not spec.source:
            raise ValueError(f"Dataset {key!r} has no downloadable source")
        _download(spec.source, full)
    if spec.smoke == "locomo":
        payload = json.loads(full.read_text())
        smoke = locomo_smoke_path(root)
        smoke.write_text(json.dumps(slice_locomo_smoke(payload), ensure_ascii=False, indent=2))
        return {"full": full, "smoke": smoke}
    if spec.smoke == "shopping":
        rows = [json.loads(line) for line in full.read_text().splitlines() if line.strip()]
        smoke = shopping_smoke_path(root)
        smoke.parent.mkdir(parents=True, exist_ok=True)
        smoke.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in slice_shopping_smoke(rows)) + "\n"
        )
        return {"full": full, "smoke": smoke}
    return {"full": full}
