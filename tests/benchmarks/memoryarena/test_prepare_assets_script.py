"""Offline preparation-script manifests and validation use real filesystem artifacts."""

import json
import runpy
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import JsonValue, TypeAdapter

SCRIPT = Path(__file__).resolve().parents[3] / "configs/memoryarena/prepare_assets.py"


def test_math_manifest_selects_complete_row_and_hashes_written_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {"id": 1, "questions": ["only one"], "answers": ["1"]},
        {"id": 9, "questions": ["a", "b"], "answers": ["2", "3"]},
        {"id": 2, "questions": ["c", "d"], "answers": ["4", "5"]},
    ]
    monkeypatch.setitem(sys.modules, "datasets", SimpleNamespace(load_dataset=lambda *a, **kw: rows))
    module = runpy.run_path(str(SCRIPT))
    prepare = cast(Callable[[Path], dict[str, JsonValue]], module["math_sample"])
    result = prepare(tmp_path)
    assert result["id"] == 2 and result["rounds"] == 2
    written = tmp_path / "math-complete-sample.json"
    assert json.loads(written.read_text()) == [rows[2]]
    assert result["sha256"] == module["sha256"](written)
    assert TypeAdapter(dict[str, JsonValue]).validate_python(result) == result


def test_shopping_subset_manifest_preserves_nested_json_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "shopping"
    target.mkdir()
    (target / "items_shuffle.json").write_text('[{"asin":"first"},{"asin":"second"}]')
    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=lambda *a, **kw: None)
    )
    monkeypatch.setitem(
        sys.modules, "ijson", SimpleNamespace(items=lambda handle, *a, **kw: iter(json.load(handle)))
    )
    module = runpy.run_path(str(SCRIPT))
    prepare = cast(Callable[[Path, int | None], dict[str, JsonValue]], module["shopping"])
    result = prepare(tmp_path, 1)
    subset = result["transport_only_subset"]
    assert isinstance(subset, dict) and subset["products"] == 1
    assert json.loads((target / "items-first1-smoke.json").read_text()) == [{"asin": "first"}]
    assert TypeAdapter(dict[str, JsonValue]).validate_python(result) == result


def test_script_rejects_invalid_subset_before_preparing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "uncreated"
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--scene", "shopping", "--shopping-smoke-limit", "0", "--output", str(target)],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exc.value.code == 2
    assert not target.exists()
