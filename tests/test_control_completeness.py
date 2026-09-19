"""Incomplete matching evidence must never imply a verified controlled comparison."""

import json
from pathlib import Path

import pytest

from dumemeval.comparison import compare_runs, load_run
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
