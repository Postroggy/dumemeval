"""DatasetLoader 层：统一从多种数据源加载评测数据。

设计要点：
- 三种 source：local（本地 Dataset/ 路径）/ hf（HuggingFace）/ git（git repo + commit 锁定）
- 版本锁定保证可复现（git commit / hf commit / 文件 hash）
- DatasetFactory 按 config 的 source.type 创建 loader，评测代码不感知数据源
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar


class DatasetLoadError(Exception):
    pass


# ── 加载结果 ────────────────────────────────────────────────────────────────


class Dataset:
    """一次加载的结果：数据 + 元信息（版本锁定用）。"""

    def __init__(
        self,
        data: Any,
        source_type: str,
        source_ref: str = "",
        version: str = "",
    ):
        self.data = data
        self.source_type = source_type
        self.source_ref = source_ref  # 如本地路径 / hf repo / git url
        self.version = version  # 锁定版本（commit / hash）

    def __repr__(self) -> str:
        return f"<Dataset source={self.source_type} ref={self.source_ref} v={self.version}>"


# ── Loader 基类 ─────────────────────────────────────────────────────────────


class BaseDatasetLoader(ABC):
    """数据集加载器基类。子类实现一种数据源。"""

    source_type: str = ""

    def __init__(self, spec: dict[str, Any]):
        self.spec = spec

    @abstractmethod
    def load(self) -> Dataset:
        """加载数据并返回带版本信息的 Dataset。"""

    def _hash_file(self, path: Path, chunk: int = 65536) -> str:
        """计算文件 sha256（本地数据版本锁定的兜底）。"""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while block := f.read(chunk):
                h.update(block)
        return h.hexdigest()[:12]


# ── 本地路径 Loader ─────────────────────────────────────────────────────────


class LocalPathLoader(BaseDatasetLoader):
    """本地路径数据源（如 Dataset/ 目录）。

    spec:
        path: 数据文件或目录路径（支持相对/绝对）
        format: 可选（json/jsonl/csv/目录），默认按扩展名推断
    """

    source_type = "local"

    def load(self) -> Dataset:
        raw_path = str(self.spec.get("path") or "")
        name = self.spec.get("name")
        path = Path(raw_path).expanduser() if raw_path else None
        if path is None or not path.exists():
            if name:
                from .prepare import dataset_names, resolve_dataset

                resolved = resolve_dataset(str(name))
                if resolved is not None:
                    path = resolved
                else:
                    raise DatasetLoadError(
                        f"Local dataset not found: {path or name!r}"
                        f"（name={name!r} 未命中仓库捆绑 data/smoke 或 prepare 缓存）\n"
                        f"  可用 name: {sorted(dataset_names())}\n"
                        f"  或先 `dumemeval prepare` 下载，或设 DUMEMEVAL_DATA_DIR，或用显式 path"
                    )
            else:
                raise DatasetLoadError(f"Local dataset not found: {path}")

        fmt = self.spec.get("format", "").lower()
        if path.is_dir():
            return self._load_dir(path)
        return self._load_file(path, fmt)

    def _load_file(self, path: Path, fmt: str = "") -> Dataset:
        if not fmt:
            fmt = path.suffix.lstrip(".").lower()
        if fmt == "json":
            data = json.loads(path.read_text())
        elif fmt == "jsonl":
            data = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        elif fmt == "csv":
            import csv

            with open(path, newline="") as f:
                data = list(csv.DictReader(f))
        else:
            # 文本兜底
            data = path.read_text()
        return Dataset(
            data=data,
            source_type=self.source_type,
            source_ref=str(path),
            version=self._hash_file(path),
        )

    def _load_dir(self, path: Path) -> Dataset:
        """加载目录：返回 {文件名: 内容}，并聚合 hash 做版本。"""
        contents: dict[str, Any] = {}
        for p in sorted(path.rglob("*")):
            if p.is_file():
                try:
                    if p.suffix in (".json", ".jsonl"):
                        contents[str(p.relative_to(path))] = (
                            json.loads(p.read_text())
                            if p.suffix == ".json"
                            else [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
                        )
                    else:
                        contents[str(p.relative_to(path))] = p.read_text()
                except Exception as e:
                    raise DatasetLoadError(f"Failed to load {p}: {e}") from e
        if not contents:
            raise DatasetLoadError(f"Empty dataset directory: {path}")
        return Dataset(
            data=contents,
            source_type=self.source_type,
            source_ref=str(path),
            version="-".join(self._hash_file(p) for p in sorted(path.rglob("*")) if p.is_file())[:16],
        )


# ── HuggingFace Loader ──────────────────────────────────────────────────────


class HFDatasetLoader(BaseDatasetLoader):
    """HuggingFace 数据源（hf_dataset + hf_config + hf_split）。

    spec:
        dataset: HF repo id（如 "ZexueHe/memoryarena"）
        config: 可选，HF config 名（如 "formal_reasoning_math"）
        split: 可选，默认 "test"
        revision: 可选，commit 锁定
    """

    source_type = "hf"

    def load(self) -> Dataset:
        try:
            from datasets import load_dataset
        except ImportError as e:
            raise DatasetLoadError(
                "HFDatasetLoader requires `datasets` package. Install with: pip install datasets"
            ) from e

        dataset_id = self.spec.get("dataset", "")
        if not dataset_id:
            raise DatasetLoadError("HF loader requires spec.dataset (repo id)")
        try:
            ds = load_dataset(
                dataset_id,
                self.spec.get("config"),
                split=self.spec.get("split", "test"),
                revision=self.spec.get("revision"),
            )
        except Exception as e:
            raise DatasetLoadError(f"Failed to load HF dataset {dataset_id}: {e}") from e
        return Dataset(
            data=ds,
            source_type=self.source_type,
            source_ref=dataset_id,
            version=self.spec.get("revision", "latest"),
        )


# ── Git Loader ──────────────────────────────────────────────────────────────


class GitDatasetLoader(BaseDatasetLoader):
    """Git 数据源（git_url + commit 锁定 + path 子目录）。

    spec:
        repo: git 仓库 URL
        commit: 锁定 commit（必填，保证可复现）
        path: 仓库内子路径（可选）
        cache_dir: 缓存目录（默认 ~/.cache/dumemeval/datasets）
    """

    source_type = "git"

    def load(self) -> Dataset:
        import subprocess
        import tempfile

        repo = self.spec.get("repo", "")
        commit = self.spec.get("commit", "")
        sub_path = self.spec.get("path", "")
        if not repo or not commit:
            raise DatasetLoadError("Git loader requires spec.repo and spec.commit")
        cache_dir = Path(self.spec.get("cache_dir", "~/.cache/dumemeval/datasets")).expanduser()
        # 用 repo+commit 做缓存目录名
        repo_slug = repo.replace("/", "_").replace(":", "_")
        clone_dir = cache_dir / f"{repo_slug}@{commit}"
        if not clone_dir.exists():
            with tempfile.TemporaryDirectory(
                dir=cache_dir.parent if cache_dir.parent.exists() else None
            ) as tmp:
                # clone 到临时目录再挪到缓存（原子化）
                tmp_clone = Path(tmp) / "repo"
                subprocess.run(
                    ["git", "clone", "--quiet", "--depth", "1", "--branch", commit, repo, str(tmp_clone)],
                    check=True,
                    capture_output=True,
                )
                # commit 可能是 tag/branch 名而非 hash，尝试 checkout 精确 commit
                subprocess.run(
                    ["git", "-C", str(tmp_clone), "checkout", "--quiet", commit],
                    check=True,
                    capture_output=True,
                )
                clone_dir.parent.mkdir(parents=True, exist_ok=True)
                tmp_clone.rename(clone_dir)

        root = clone_dir / sub_path if sub_path else clone_dir
        if not root.exists():
            raise DatasetLoadError(f"Git dataset subpath not found: {root}")

        # 复用本地 loader 的逻辑读内容
        loader = LocalPathLoader({"path": str(root)})
        ds = loader.load()
        ds.source_type = self.source_type
        ds.source_ref = repo
        ds.version = commit
        return ds


# ── Factory ─────────────────────────────────────────────────────────────────


class DatasetFactory:
    """按 config 的 source 创建 loader（注册表分发，调用方不感知数据源）。"""

    _LOADERS: ClassVar[dict[str, type[BaseDatasetLoader]]] = {
        "local": LocalPathLoader,
        "hf": HFDatasetLoader,
        "git": GitDatasetLoader,
    }

    @classmethod
    def create(cls, spec: dict[str, Any]) -> BaseDatasetLoader:
        source_type = spec.get("type", "local")
        loader_cls = cls._LOADERS.get(source_type)
        if loader_cls is None:
            raise DatasetLoadError(
                f"Unknown dataset source type: {source_type!r}. Supported: {list(cls._LOADERS)}"
            )
        return loader_cls(spec)

    @classmethod
    def register(cls, source_type: str, loader_cls: type[BaseDatasetLoader]) -> None:
        """注册自定义 loader（扩展点）。"""
        cls._LOADERS[source_type] = loader_cls
