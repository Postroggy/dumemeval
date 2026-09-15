"""Reproduction templates preserve matched prompts and isolated memory protocols."""

import json
from pathlib import Path

import pytest

from dumemeval.artifacts.controls import experiment_controls
from dumemeval.cli.run import _build_tasks
from dumemeval.config import load_config
from dumemeval.core.config import DatasetSpec
from tests.test_memoryarena_contracts import raw_case

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("template", ["controlled-math-hermes", "hermes-memory-link"])
def test_hermes_matched_templates(template: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    marker = "diagnostic-marker-for-the-first-session"
    for key, value in {
        "DUMEMEVAL_PROXY_KEY": "fixture-key",
        "MEMORYARENA_MARKER": marker,
        "MEMORYARENA_ARM": "on",
        "MEMORYARENA_PROTOCOL": "memory_session_transfer",
        "MEMORYARENA_MEMORY_TYPE": "directory",
        "MEMORYARENA_MEMORY_INJECT": "true",
    }.items():
        monkeypatch.setenv(key, value)
    path = ROOT / "configs" / "memoryarena" / f"{template}.yaml"
    on = load_config(path)
    monkeypatch.setenv("MEMORYARENA_ARM", "off")
    monkeypatch.setenv("MEMORYARENA_PROTOCOL", "test_only")
    monkeypatch.setenv("MEMORYARENA_MEMORY_TYPE", "none")
    monkeypatch.setenv("MEMORYARENA_MEMORY_INJECT", "false")
    off = load_config(path)
    assert on.agent == off.agent and on.execution == off.execution and on.judging == off.judging
    assert on.agent.runtime == "hermes" and on.agent.version == "0.21.3"
    assert on.agent.skills_dir is None
    assert on.output.dir != off.output.dir
    if template == "controlled-math-hermes":
        data = tmp_path / "math.json"
        data.write_text(json.dumps(raw_case("math")), encoding="utf-8")
        on.task.data = off.task.data = DatasetSpec(type="local", path=str(data))
    else:
        assert on.task.benchmark is None
        assert marker in on.task.sessions[0].instruction
        assert marker not in on.task.sessions[1].instruction
    tasks_on, tasks_off = _build_tasks(on), _build_tasks(off)
    assert [s.instruction for s in tasks_on[0].sessions] == [s.instruction for s in tasks_off[0].sessions]
    assert all(not s.memory_inject for s in tasks_off[0].sessions)
    assert experiment_controls(on, tasks_on) == experiment_controls(off, tasks_off)
