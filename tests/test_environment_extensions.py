"""Preparation and control evidence must work for independently registered environments."""

import json
from pathlib import Path
from typing import Any

import pytest

from dumemeval.artifacts.controls import observed_controls
from dumemeval.artifacts.provenance import snapshot_run
from dumemeval.cli import main
from dumemeval.comparison.service import comparability_warnings
from dumemeval.core.config import ExperimentConfig
from dumemeval.environments import HttpTaskEnvironment, register_task_environment
from dumemeval.models import EvalTask, RunRef, RunSummary, TaskEnvSpec
from dumemeval.models.environment import EnvironmentControls
from dumemeval.task_environments.base import EnvironmentPreparation
from dumemeval.task_environments.prepare import prepare_environment


class FixturePreparation(EnvironmentPreparation):
    inspected: str
    clone_requested: bool


class FixtureEnvironment(HttpTaskEnvironment):
    name = "fixture-independent-environment"
    observed_control_keys = ("observed_environment",)

    def prepare(self, spec: TaskEnvSpec, *, clone: bool = False) -> EnvironmentPreparation:
        ready = bool(spec.config.get("ready", True))
        return FixturePreparation(
            ready=ready,
            missing=[] if ready else ["fixture input unavailable"],
            inspected=str(spec.config["input"]),
            clone_requested=clone,
        )


def config(output: Path) -> ExperimentConfig:
    register_task_environment(FixtureEnvironment)
    return ExperimentConfig.model_validate(
        {
            "experiment": {"name": "external", "protocol": "test_only"},
            "memory": {"name": "none", "type": "none"},
            "task": {
                "sessions": [{"instruction": "inspect", "memory_inject": False}],
                "task_environment": {"type": FixtureEnvironment.name, "config": {"input": "fixture"}},
            },
            "output": {"dir": str(output)},
        }
    )


def write_runtime(root: Path, task: str, controls: dict[str, Any] | None, *, port: int = 1) -> None:
    path = root / "environments" / task / "runtime.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"port": port}
    if controls is not None:
        payload["controls"] = controls
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize("ready", [True, False])
def test_cli_preparation_routes_to_registered_provider(tmp_path: Path, ready: bool) -> None:
    cfg = config(tmp_path / "output")
    assert cfg.task.task_environment is not None
    cfg.task.task_environment.config["ready"] = ready
    path = tmp_path / "config.json"
    path.write_text(cfg.model_dump_json(), encoding="utf-8")
    assert main(["prepare", "--environment-config", str(path), "--clone-reference"]) == (0 if ready else 1)
    report = json.loads((Path(cfg.output.dir) / "preparation.json").read_text(encoding="utf-8"))
    assert report == {
        "ready": ready,
        "missing": [] if ready else ["fixture input unavailable"],
        "inspected": "fixture",
        "clone_requested": True,
    }


@pytest.mark.parametrize("provider", [None, "http"])
def test_unsupported_preparation_is_explicit(tmp_path: Path, provider: str | None) -> None:
    cfg = config(tmp_path)
    cfg.task.task_environment = TaskEnvSpec(type=provider) if provider else None
    with pytest.raises(
        ValueError, match=r"requires task.task_environment|does not support managed preparation"
    ):
        prepare_environment(cfg)
    assert not (tmp_path / "preparation.json").exists()


def test_registered_provider_requires_observed_evidence(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    task = cfg.to_eval_task()
    provenance = snapshot_run(cfg, output_dir=tmp_path, config_path="fixture.json", mock=True, tasks=[task])
    assert provenance.controls["observed_environment"] == "not-observed"
    run = RunRef(label="external", path=tmp_path, summary=RunSummary(n_tasks=1), provenance=provenance)
    assert any(
        "observed_environment" in warning and "unverified" in warning
        for warning in comparability_warnings([run, run.model_copy(update={"label": "other"})])
    )

    controls = EnvironmentControls(task_id=task.name, fingerprint={"asset": "abc"})
    write_runtime(tmp_path, task.name, controls.model_dump())
    observed = snapshot_run(cfg, output_dir=tmp_path, config_path="fixture.json", mock=True, tasks=[task])
    assert observed.controls["observed_environment"] != "not-observed"

    second = EvalTask(name="second", task_environment=task.task_environment)
    partial = snapshot_run(
        cfg, output_dir=tmp_path, config_path="fixture.json", mock=True, tasks=[task, second]
    )
    assert partial.controls["observed_environment"] == "not-observed"


def test_only_provider_selected_stable_fields_affect_controls(tmp_path: Path) -> None:
    controls = EnvironmentControls(task_id="one", fingerprint={"asset": "abc"})
    write_runtime(tmp_path, "one", controls.model_dump(), port=1)
    original = observed_controls(tmp_path)
    write_runtime(tmp_path, "one", controls.model_dump(), port=2)
    assert observed_controls(tmp_path) == original
    controls.fingerprint["asset"] = "changed"
    write_runtime(tmp_path, "one", controls.model_dump(), port=2)
    assert observed_controls(tmp_path)["observed_environment"] != original["observed_environment"]


@pytest.mark.parametrize("evidence", [None, {}, {"task_id": "one", "fingerprint": {}}])
def test_legacy_or_missing_runtime_control_evidence_is_unverified(tmp_path: Path, evidence: Any) -> None:
    write_runtime(tmp_path, "one", evidence)
    assert observed_controls(tmp_path)["observed_environment"] == "not-observed"


def test_uncontrolled_factors_are_reported_without_scene_specific_logic(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    task = cfg.to_eval_task()
    controls = EnvironmentControls(
        task_id=task.name, fingerprint={"asset": "abc"}, uncontrolled=["external_clock"]
    )
    write_runtime(tmp_path, task.name, controls.model_dump())
    provenance = snapshot_run(cfg, output_dir=tmp_path, config_path="fixture.json", mock=True, tasks=[task])
    assert provenance.controls["external_clock"] == "not-controlled"
    run = RunRef(label="external", path=tmp_path, summary=RunSummary(n_tasks=1), provenance=provenance)
    assert any(
        "external_clock" in warning
        for warning in comparability_warnings([run, run.model_copy(update={"label": "other"})])
    )


def test_duplicate_environment_identity_is_unverified(tmp_path: Path) -> None:
    controls = EnvironmentControls(task_id="one", fingerprint={"asset": "abc"}).model_dump()
    for directory in ["first", "second"]:
        write_runtime(tmp_path, directory, controls)
    assert observed_controls(tmp_path)["observed_environment"] == "not-observed"
