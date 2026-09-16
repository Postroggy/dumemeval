"""Incomplete matching evidence must never imply a verified controlled comparison."""

import json
import zipfile
from pathlib import Path

import pytest

from dumemeval.comparison import compare_runs, load_run
from dumemeval.comparison.report import write_comparison
from dumemeval.models import RunRef
from tests.test_comparison import _write_run

# Test the public contract independently of the comparator's required-field constant.
COMPLETE_CONTROLS = dict.fromkeys(
    (
        "tasks",
        "dataset",
        "agent",
        "agent_skills",
        "judge",
        "runtime",
        "task_environment",
        "code",
        "observed_prompts",
    ),
    "a" * 64,
)


def written_run(root: Path, label: str, controls: dict[str, str]) -> RunRef:
    path = _write_run(root, label, metrics={"locomo.f1": 0.5})
    config_path = path / "experiment_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["provenance"]["controls"] = controls
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return load_run(path)


@pytest.mark.parametrize("field", ["observed_prompts", "agent_skills"])
@pytest.mark.parametrize("both", [False, True], ids=["one-arm", "both-arms"])
def test_absent_required_control_names_affected_runs(tmp_path: Path, field: str, both: bool) -> None:
    missing = {key: value for key, value in COMPLETE_CONTROLS.items() if key != field}
    runs = [
        written_run(tmp_path, "on", missing),
        written_run(tmp_path, "off", missing if both else COMPLETE_CONTROLS),
    ]
    warnings = compare_runs(runs).warnings
    affected = ["on", "off"] if both else ["on"]
    for label in affected:
        assert any(
            f"{label}:" in warning and field in warning and "unverified" in warning for warning in warnings
        )


@pytest.mark.parametrize("value", ["", "   ", "not-observed"])
def test_empty_or_unobserved_required_control_is_unverified(tmp_path: Path, value: str) -> None:
    controls = {**COMPLETE_CONTROLS, "observed_prompts": value}
    runs = [written_run(tmp_path, label, controls) for label in ["on", "off"]]
    assert any("unverified" in warning for warning in compare_runs(runs).warnings)


def test_only_new_fields_do_not_satisfy_the_required_control_contract(tmp_path: Path) -> None:
    controls = {key: COMPLETE_CONTROLS[key] for key in ["observed_prompts", "agent_skills"]}
    runs = [written_run(tmp_path, label, controls) for label in ["on", "off"]]
    warnings = compare_runs(runs).warnings
    for field in ("tasks", "dataset", "agent", "judge", "runtime", "task_environment", "code"):
        assert any(field in warning and "unverified" in warning for warning in warnings)


@pytest.mark.parametrize("scene", ["math", "diagnostic"])
def test_committed_hermes_reports_warn_without_changing_scores(tmp_path: Path, scene: str) -> None:
    archive = Path(__file__).resolve().parents[1] / "docs/datasets/memoryarena-hermes-evidence.zip"
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
