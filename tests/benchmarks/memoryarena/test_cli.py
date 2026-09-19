"""Five scenario templates through the real CLI with synthetic data and mock execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dumemeval.cli import main
from dumemeval.cli.run import _build_tasks
from dumemeval.config import load_config
from dumemeval.core.config import DatasetSpec
from tests.benchmarks.memoryarena.test_contracts import ADAPTERS, raw_case

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def template_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "MEMORYARENA_AGENT_MODEL": "fixture-agent",
        "MEMORYARENA_JUDGE_MODEL": "fixture-judge",
        "ANTHROPIC_AUTH_TOKEN": "fixture-not-a-secret",
        "ANTHROPIC_BASE_URL": "https://example.invalid",
        "MEMORYARENA_JAVA_HOME": "fixture-java-home-not-used-by-mock",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("scene", ADAPTERS)
def test_five_templates_run_through_cli(scene: str, template_env: None, tmp_path: Path) -> None:
    cfg = load_config(ROOT / "configs" / "memoryarena" / f"{scene}.yaml")
    assert cfg.task.data is not None
    assert cfg.task.data.revision == "da1a37c8b19280e18627ca01cf368195a5e1d92e"
    data = tmp_path / "fixture.json"
    data.write_text(json.dumps(raw_case(scene)), encoding="utf-8")
    cfg.task.data = DatasetSpec(type="local", path=str(data))
    cfg.memory.path = str(tmp_path / "memory")
    cfg.output.dir = str(tmp_path / "run")
    cfg.output.tasks_dir = str(tmp_path / "tasks")
    config = tmp_path / "config.json"
    config.write_text(cfg.model_dump_json(), encoding="utf-8")
    assert main(["run", "--config", str(config), "--mock", "--no-resume"]) == 0
    summary = json.loads((Path(cfg.output.dir) / "summary.json").read_text(encoding="utf-8"))
    assert summary["mock"] is True
    assert summary["n_tasks"] == 1
    assert (Path(cfg.output.dir) / "summary.md").is_file()
    if scene == "shopping":
        assert summary["benchmark"]["values"] == {}, "Mock text cannot become an official purchase score"


@pytest.mark.parametrize("scene", ADAPTERS)
def test_ablation_templates_align_data_agent_and_sessions(
    scene: str, template_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template = ROOT / "configs" / "memoryarena" / f"{scene}.yaml"
    enabled = load_config(template)
    monkeypatch.setenv("MEMORYARENA_ARM", "off")
    monkeypatch.setenv("MEMORYARENA_PROTOCOL", "test_only")
    monkeypatch.setenv("MEMORYARENA_MEMORY_TYPE", "none")
    disabled = load_config(template)
    assert enabled.agent == disabled.agent
    assert enabled.judging == disabled.judging
    assert enabled.execution == disabled.execution
    assert enabled.task == disabled.task
    assert enabled.output.dir != disabled.output.dir
    data = tmp_path / "fixture.json"
    data.write_text(json.dumps(raw_case(scene)), encoding="utf-8")
    for config in (enabled, disabled):
        config.task.data = DatasetSpec(type="local", path=str(data))
    tasks_on, tasks_off = _build_tasks(enabled), _build_tasks(disabled)
    assert [task.name for task in tasks_on] == [task.name for task in tasks_off]
    assert [s.instruction for s in tasks_on[0].sessions] == [s.instruction for s in tasks_off[0].sessions]
    assert all(not s.memory_inject for s in tasks_off[0].sessions)


def test_environment_overrides_preserve_adapter_defaults(template_env: None, tmp_path: Path) -> None:
    cfg = load_config(ROOT / "configs" / "memoryarena" / "shopping.yaml")
    assert cfg.task.task_environment is not None
    cfg.task.task_environment.config = {"timeout": 12}
    data = tmp_path / "fixture.json"
    data.write_text(json.dumps(raw_case("shopping")), encoding="utf-8")
    cfg.task.data = DatasetSpec(type="local", path=str(data))
    task = _build_tasks(cfg)[0]
    assert task.task_environment["config"] == {"env_name": "webshop", "timeout": 12}
