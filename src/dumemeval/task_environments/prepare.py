"""Dispatch environment preparation through the same provider registry as execution."""

from pathlib import Path

from ..core.config import ExperimentConfig
from ..environments import get_task_environment
from .base import EnvironmentPreparation


def prepare_environment(cfg: ExperimentConfig, *, clone: bool = False) -> EnvironmentPreparation:
    """Prepare a configured provider and persist its typed diagnostic report."""
    spec = cfg.task.task_environment
    if spec is None:
        raise ValueError("--environment-config requires task.task_environment")
    report = get_task_environment(spec.type).prepare(spec, clone=clone)
    output = Path(cfg.output.dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "preparation.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
