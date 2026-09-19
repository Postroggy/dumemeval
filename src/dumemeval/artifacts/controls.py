"""Stable, secret-free fingerprints for the inputs of a controlled experiment."""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from pydantic import ValidationError

from ..core.config import ExperimentConfig
from ..models import EvalTask
from ..models.environment import EnvironmentControls
from .redaction import redact_config


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def runtime_versions() -> dict[str, str]:
    packages = {}
    for package in ("dumemeval", "harbor", "anthropic", "openai", "datasets", "pydantic"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "not-installed"
    return packages


def experiment_controls(cfg: ExperimentConfig, tasks: list[EvalTask]) -> dict[str, str]:
    protocol = cfg.protocol_instance
    skills = skill_contents(cfg.agent.skills_dir)
    source = Path(__file__).resolve().parents[1]
    files = {
        str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source.rglob("*.py"))
    }
    controls = {
        name: digest(value)
        for name, value in {
            "tasks": [
                {
                    "name": t.name,
                    "data": t.data,
                    "memory_instruction": t.memory_instruction,
                    "sessions": [
                        {
                            "id": s.id,
                            "query": s.query,
                            "instruction": s.instruction,
                            "effective_memory_instruction": (
                                t.memory_instruction
                                if s.memory_inject and protocol.should_adapter_inject(s.memory_inject)
                                else "none"
                            ),
                        }
                        for s in t.sessions
                    ],
                }
                for t in tasks
            ],
            "dataset": cfg.task.data.model_dump() if cfg.task.data else {},
            "agent": redact_config(cfg.agent.model_dump()),
            "agent_skills": skills,
            "judge": redact_config(cfg.judging.model_dump()),
            "runtime": {
                "engine": cfg.execution.engine,
                "environment": redact_config(cfg.execution.environment.model_dump()),
                "packages": runtime_versions(),
            },
            "task_environment": [redact_config(t.task_environment) for t in tasks],
            "code": files,
        }.items()
    }
    if skills.get("status") == "not-observed":
        controls["agent_skills"] = "not-observed"
    return controls


def skill_contents(directory: str | None) -> dict[str, str]:
    """Hash files supplied to the runtime, including skill support files."""
    if directory is None:
        return {}
    root = Path(directory)
    if not root.is_dir():
        return {"status": "not-observed"}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def observed_controls(
    output_dir: Path, *, expected_environment_tasks: set[str] | None = None
) -> dict[str, str]:
    """Fingerprint observed implementations without ephemeral ports or task handles."""
    environments: list[EnvironmentControls] = []
    incomplete = False
    for path in sorted((output_dir / "environments").glob("*/runtime.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        try:
            control = EnvironmentControls.model_validate(data.get("controls", {}))
        except ValidationError:
            incomplete = True
            continue
        incomplete |= not control.fingerprint
        environments.append(control)
    task_ids = {control.task_id for control in environments}
    incomplete |= len(task_ids) != len(environments)
    if expected_environment_tasks is not None:
        incomplete |= task_ids != expected_environment_tasks
    environments.sort(key=lambda control: control.task_id)
    agents = []
    for path in sorted((output_dir / "trials").glob("*/agent/trajectory.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        agent = data.get("agent") or {}
        agents.append({key: agent.get(key) for key in ("name", "version", "model_name")})
    instructions = []
    for path in sorted((output_dir / "checkpoints").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        instructions.append(
            {
                "task_id": data.get("task_id"),
                "sessions": [
                    {
                        "session_id": session.get("session_id"),
                        "instruction_sha256": session.get("instruction_sha256"),
                    }
                    for session in data.get("sessions", [])
                ],
            }
        )
    return {
        "observed_environment": (
            digest([control.model_dump() for control in environments])
            if environments and not incomplete
            else "not-observed"
        ),
        "observed_agent": digest(agents) if agents else "not-observed",
        "observed_prompts": (
            digest(instructions)
            if instructions
            and all(task["sessions"] for task in instructions)
            and all(item["instruction_sha256"] for task in instructions for item in task["sessions"])
            else "not-observed"
        ),
        **{key: "not-controlled" for control in environments for key in control.uncontrolled},
    }
