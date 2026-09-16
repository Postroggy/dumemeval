"""Historical Hermes reports keep their scores and expose missing control evidence."""

import json
import zipfile
from pathlib import Path

import pytest

from dumemeval.comparison import compare_runs, load_run
from dumemeval.comparison.report import write_comparison


@pytest.mark.parametrize("scene", ["math", "diagnostic"])
def test_committed_hermes_reports_warn_without_changing_scores(tmp_path: Path, scene: str) -> None:
    archive = Path(__file__).resolve().parents[3] / "docs/datasets/memoryarena/hermes-evidence.zip"
    with zipfile.ZipFile(archive) as bundle:
        for arm in ["on", "off"]:
            directory = tmp_path / arm
            directory.mkdir()
            for name in ["summary.json", "experiment_config.json"]:
                (directory / name).write_bytes(bundle.read(f"{scene}/{arm}/{name}"))
    originals = {path: path.read_bytes() for path in tmp_path.glob("*/*.json")}
    runs = [load_run(tmp_path / arm) for arm in ["on", "off"]]
    summaries = [run.summary.model_dump(mode="json") for run in runs]
    for run in runs:
        assert run.provenance is not None
        assert {"observed_prompts", "agent_skills"}.isdisjoint(run.provenance.controls)
    comparison = compare_runs(runs, baseline="off")
    for arm in ["on", "off"]:
        assert any(
            f"{arm}:" in warning
            and "agent_skills" in warning
            and "observed_prompts" in warning
            and "unverified" in warning
            for warning in comparison.warnings
        )
    for run, summary in zip(runs, summaries, strict=True):
        assert run.summary.model_dump(mode="json") == summary
        for metric, value in run.summary.metrics.items():
            delta = comparison.delta_for(metric)
            assert delta is not None and delta.values[run.label] == value
            baseline = runs[1].summary.metrics.get(metric)
            if baseline is not None:
                assert delta.delta(run.label) == pytest.approx(value - baseline)
    output = write_comparison(comparison, runs, tmp_path / "comparison")
    assert (
        json.loads((output / "comparison.json").read_text(encoding="utf-8"))["warnings"]
        == comparison.warnings
    )
    markdown = (output / "comparison.md").read_text(encoding="utf-8")
    assert "agent_skills" in markdown and "observed_prompts" in markdown and "unverified" in markdown
    assert all(path.read_bytes() == value for path, value in originals.items())
