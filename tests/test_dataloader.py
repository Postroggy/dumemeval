"""测试：DatasetLoader。"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.datasets.loader import (
    DatasetFactory,
    DatasetLoadError,
    LocalPathLoader,
)


class TestLocalPathLoader:
    def test_load_json(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        p.write_text(json.dumps({"a": 1}))
        ds = LocalPathLoader({"path": str(p)}).load()
        assert ds.data == {"a": 1}
        assert ds.source_type == "local"
        assert ds.version  # hash 非空

    def test_load_jsonl(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text(json.dumps({"q": 1}) + "\n" + json.dumps({"q": 2}) + "\n")
        ds = LocalPathLoader({"path": str(p)}).load()
        assert len(ds.data) == 2

    def test_load_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "data"
        d.mkdir()
        (d / "a.json").write_text(json.dumps({"x": 1}))
        (d / "b.txt").write_text("hello")
        ds = LocalPathLoader({"path": str(d)}).load()
        assert set(ds.data.keys()) == {"a.json", "b.txt"}
        assert ds.data["b.txt"] == "hello"

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DatasetLoadError, match="not found"):
            LocalPathLoader({"path": str(tmp_path / "nope")}).load()

    def test_name_resolves_bundled_smoke(self) -> None:
        """name=locomo_smoke → 仓库捆绑 data/smoke/locomo_smoke.json（零下载）。"""
        ds = LocalPathLoader({"type": "local", "name": "locomo_smoke"}).load()
        assert ds.data  # 非空
        assert "conversation" in ds.data[0]  # LoCoMo 结构

    def test_name_unknown_raises_with_hint(self) -> None:
        with pytest.raises(DatasetLoadError, match=r"no_such_dataset"):
            LocalPathLoader({"type": "local", "name": "no_such_dataset"}).load()

    def test_name_cache_hit(self, tmp_path: Path, monkeypatch: Any) -> None:
        """name 解析优先捆绑，其次 prepare 缓存（DUMEMEVAL_DATA_DIR 覆盖）。"""
        cache = tmp_path / "cache"
        (cache / "locomo").mkdir(parents=True)
        (cache / "locomo" / "locomo10.json").write_text(json.dumps([{"sample_id": "c"}]))
        monkeypatch.setenv("DUMEMEVAL_DATA_DIR", str(cache))
        from dumemeval.datasets.prepare import resolve_dataset

        resolved = resolve_dataset("locomo")
        assert resolved is not None
        assert resolved.name == "locomo10.json"
        assert resolved.parent == cache / "locomo"


class TestFactory:
    def test_create_local(self) -> None:
        assert isinstance(DatasetFactory.create({"type": "local"}), LocalPathLoader)

    def test_create_unknown_raises(self) -> None:
        with pytest.raises(DatasetLoadError, match="Unknown dataset source type"):
            DatasetFactory.create({"type": "bogus"})

    def test_default_type_is_local(self) -> None:
        assert isinstance(DatasetFactory.create({}), LocalPathLoader)
