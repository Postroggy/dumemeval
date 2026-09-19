"""Asset preparation must inspect the implementation and paths actually selected."""

from pathlib import Path

import pytest

from dumemeval.benchmarks.memoryarena.environment.config import ArenaRuntimeConfig
from dumemeval.benchmarks.memoryarena.environment.prepare import required_assets


def test_bm25_uses_directory_without_dense_index_maps(tmp_path: Path) -> None:
    config = ArenaRuntimeConfig(
        reference=tmp_path,
        env_name="browsecomp-plus",
        tools_config={
            "searcher_type": "bm25",
            "snippet_max_tokens": 0,
            "searcher_args": {"index_path": str(tmp_path / "lucene")},
        },
    )
    assert required_assets(config) == [str(tmp_path / "lucene")]


def test_tokenized_search_requires_a_pinned_cache(tmp_path: Path) -> None:
    config = ArenaRuntimeConfig(
        reference=tmp_path,
        env_name="browsecomp-plus",
        tools_config={"searcher_type": "bm25", "searcher_args": {"index_path": str(tmp_path / "lucene")}},
    )
    assert any("tokenizer_revision" in path for path in required_assets(config))
    config.tools_config["tokenizer_revision"] = "f" * 40
    config.service_env["HF_HUB_CACHE"] = str(tmp_path / "cache")
    paths = required_assets(config)
    assert str(tmp_path / "cache/models--Qwen--Qwen3-0.6B/refs/main") in paths
    assert str(tmp_path / "cache/models--Qwen--Qwen3-0.6B/snapshots" / ("f" * 40)) in paths


def test_shopping_fingerprints_explicit_items_file(tmp_path: Path) -> None:
    config = ArenaRuntimeConfig(
        reference=tmp_path,
        env_name="webshop",
        service_env={"MEMORYARENA_WEBSHOP_ITEMS_FILE": str(tmp_path / "selected.json")},
    )
    paths = required_assets(config)
    assert str(tmp_path / "selected.json") in paths
    assert not any("items_shuffle.json" in path for path in paths)


def test_search_rejects_non_numeric_snippet_limit(tmp_path: Path) -> None:
    config = ArenaRuntimeConfig(
        reference=tmp_path,
        env_name="browsecomp-plus",
        tools_config={
            "searcher_type": "bm25",
            "searcher_args": {"index_path": "index"},
            "snippet_max_tokens": "512",
        },
    )
    with pytest.raises(ValueError, match="snippet_max_tokens"):
        required_assets(config)
    config.tools_config["snippet_max_tokens"] = None
    assert required_assets(config) == ["index"]
