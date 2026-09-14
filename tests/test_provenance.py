"""测试：实验溯源（git / 配置脱敏 / 复现命令）——报告可复现的骨架。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dumemeval.core.config import ExperimentConfig
from dumemeval.provenance import collect_git, redact_config, reproduce_command, snapshot_run


def test_redact_config_strips_secrets() -> None:
    raw = {
        "judging": {"api_key_env": "OPENAI_API_KEY", "model": "gpt-4o-mini"},
        "execution": {"environment": {"env": {"ANTHROPIC_AUTH_TOKEN": "sk-secret", "ANTHROPIC_MODEL": "x"}}},
    }
    out = redact_config(raw)
    assert isinstance(out, dict)
    judging = out["judging"]
    assert isinstance(judging, dict)
    assert judging["model"] == "gpt-4o-mini"
    exec_env = out["execution"]["environment"]["env"]
    assert isinstance(exec_env, dict)
    assert exec_env["ANTHROPIC_AUTH_TOKEN"] == "***"
    assert exec_env["ANTHROPIC_MODEL"] == "x"


def test_reproduce_command_includes_mock_and_paths() -> None:
    cmd = reproduce_command(config_path="configs/foo.yaml", output_dir="results/run1", mock=True)
    assert "dumemeval run" in cmd
    assert "--config configs/foo.yaml" in cmd
    assert "--output results/run1" in cmd
    assert "--mock" in cmd


def test_reproduce_command_omits_mock_when_real() -> None:
    cmd = reproduce_command(config_path="c.yaml", output_dir="out", mock=False)
    assert "--mock" not in cmd


def test_collect_git_soft_fails_outside_repo(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    snap = collect_git(tmp_path)
    assert snap.commit is None
    assert snap.dirty is False


def test_snapshot_run_writes_experiment_config(tmp_path: Path) -> None:
    cfg = ExperimentConfig.model_validate(
        {
            "experiment": {"name": "demo", "protocol": "memory_session_transfer"},
            "memory": {"name": "m", "type": "directory"},
            "task": {"sessions": [{"instruction": "s1"}, {"instruction": "s2"}]},
            "judging": {"type": "rule", "num_runs": 3, "skip_failed": True},
        }
    )
    prov = snapshot_run(
        cfg,
        output_dir=tmp_path,
        config_path="configs/demo.yaml",
        mock=True,
        n_concurrent=2,
    )
    path = tmp_path / "experiment_config.json"
    assert path.exists()
    text = path.read_text()
    assert "demo" in text
    assert prov.mock is True
    assert prov.judging_num_runs == 3
    assert "--mock" in prov.reproduce
    assert prov.n_concurrent == 2
