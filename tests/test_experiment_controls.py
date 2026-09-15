"""Prompt-policy changes must be visible in the public comparison warnings."""

from pathlib import Path
from typing import Literal

import pytest

from dumemeval.artifacts.controls import experiment_controls
from dumemeval.comparison.service import comparability_warnings
from dumemeval.core.config import ExperimentConfig
from dumemeval.models import RunProvenance, RunRef, RunSummary


def _config() -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "experiment": {"name": "control", "protocol": "memory_session_transfer"},
            "memory": {"name": "control", "type": "directory"},
            "task": {
                "sessions": [{"instruction": "Question one"}, {"instruction": "Question two"}],
                "memory_instruction": "none",
            },
        }
    )


def _run(label: str, controls: dict[str, str]) -> RunRef:
    return RunRef(
        label=label,
        path=Path(label),
        summary=RunSummary(n_tasks=1),
        provenance=RunProvenance(controls=controls),
    )


@pytest.mark.parametrize("policy", ["location", "proactive"])
def test_changed_effective_prompt_policy_warns(policy: Literal["location", "proactive"]) -> None:
    cfg = _config()
    task = cfg.to_eval_task()
    original = _run("original", experiment_controls(cfg, [task]))
    # The adapter's effective task is authoritative even if the config is unchanged.
    task.memory_instruction = policy
    changed = _run("changed", experiment_controls(cfg, [task]))
    assert comparability_warnings([original, changed]) == [
        "Controlled input differs: tasks; this comparison is not a controlled ablation"
    ]


def test_matched_prompt_on_off_remains_comparable() -> None:
    on = _config()
    off = on.model_copy(deep=True)
    off.experiment.protocol = "test_only"
    off.memory.type = "none"
    runs = [
        _run(label, experiment_controls(cfg, [cfg.to_eval_task()]))
        for label, cfg in [("on", on), ("off", off)]
    ]
    assert comparability_warnings(runs) == []
