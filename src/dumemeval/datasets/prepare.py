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

}


def dataset_names() -> list[str]:
    """已注册的逻辑数据名。"""
    return sorted(DATASET_REGISTRY)


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




def prepare_dataset(name: str, *, root: Path | None = None, force: bool = False) -> dict[str, Path]:
    """按注册的 DatasetSpec 准备数据；没有 smoke 转换时只返回 full。"""
    key = name
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
    return {"full": full}


def prepare_locomo(*, root: Path | None = None, force: bool = False) -> dict[str, Path]:
    root = root or cache_root()
    full = locomo_full_path(root)
    smoke = locomo_smoke_path(root)
    if force or not full.exists():
        _download(DATASET_REGISTRY["locomo"]["source"], full)
    payload = json.loads(full.read_text())
    if not isinstance(payload, list):
        raise ValueError(f"unexpected locomo shape: {type(payload)}")
    smoke.write_text(json.dumps(slice_locomo_smoke(payload), ensure_ascii=False, indent=2))
    return {"full": full, "smoke": smoke}


