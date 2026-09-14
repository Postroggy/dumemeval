"""测试：CLI 入口（main / ground truth 解析）。"""

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.cli import main
from dumemeval.models import MemoryFact
from dumemeval.pipeline import parse_ground_truth as _parse_ground_truth


class TestParseGroundTruth:
    def test_empty(self) -> None:
        assert _parse_ground_truth("") == []

    def test_plain_text_lines(self) -> None:
        facts = _parse_ground_truth("fact1\nfact2\n")
        assert len(facts) == 2
        assert all(isinstance(f, MemoryFact) for f in facts)
        assert facts[0].fact == "fact1"

    def test_json_list(self) -> None:
        facts = _parse_ground_truth('[{"fact": "latte", "category": "preference"}]')
        assert len(facts) == 1
        assert facts[0].fact == "latte"
        assert facts[0].category == "preference"

    def test_blank_lines_skipped(self) -> None:
        facts = _parse_ground_truth("a\n\nb\n")
        assert len(facts) == 2


class TestMain:
    def test_unknown_command(self) -> None:
        """未知子命令 → argparse SystemExit(2)。"""
        with pytest.raises(SystemExit) as exc_info:
            main(["bogus"])
        assert exc_info.value.code == 2

    def test_run_missing_config(self, capsys: Any) -> None:
        with pytest.raises(FileNotFoundError):
            main(["run", "--config", "/nonexistent.yaml"])

    def test_run_mock_end_to_end(self, tmp_path: Path) -> None:
        """--mock 全流程端到端（配置→runner→quality→report）。"""
        cfg = tmp_path / "eval.yaml"
        cfg.write_text(
            f"""
experiment:
  name: test-cli
  protocol: memory_session_transfer
memory:
  name: cli-mem
  type: directory
  path: {tmp_path / "memory"}
task:
  sessions:
    - instruction: "记住偏好"
    - instruction: "应用偏好"
  memory_ground_truth: "latte"
judging:
  type: rule
execution:
  engine: mock
output:
  dir: {tmp_path / "results"}
  tasks_dir: {tmp_path / "tasks"}
"""
        )
        rc = main(["run", "--config", str(cfg), "--mock", "--output", str(tmp_path / "results")])
        assert rc == 0
        # 报告应生成
        assert (tmp_path / "results" / "test-cli__cli-mem" / "report.md").exists()
        assert (tmp_path / "results" / "test-cli__cli-mem" / "result.json").exists()
        # task 级 checkpoint（供 --resume 跳过）
        assert (tmp_path / "results" / "checkpoints" / "test-cli.json").exists()
        snap = tmp_path / "results" / "experiment_config.json"
        assert snap.exists()
        md = (tmp_path / "results" / "test-cli__cli-mem" / "report.md").read_text()
        assert "mock" in md.lower()
        assert "dumemeval run" in md
        summary = (tmp_path / "results" / "summary.md").read_text()
        assert "不可引用" in summary

    def test_run_no_resume_flag(self, tmp_path: Path) -> None:
        """--no-resume 强制重跑，覆盖已有 checkpoint。"""
        cfg = tmp_path / "eval.yaml"
        cfg.write_text(
            f"""
experiment:
  name: test-cli
  protocol: memory_session_transfer
memory:
  name: cli-mem
  type: directory
  path: {tmp_path / "memory"}
task:
  sessions:
    - instruction: "记住偏好"
    - instruction: "应用偏好"
judging:
  type: rule
execution:
  engine: mock
output:
  dir: {tmp_path / "results"}
  tasks_dir: {tmp_path / "tasks"}
"""
        )
        first = main(["run", "--config", str(cfg), "--mock", "--output", str(tmp_path / "results")])
        assert first == 0
        rc = main(
            [
                "run",
                "--config",
                str(cfg),
                "--mock",
                "--no-resume",
                "--output",
                str(tmp_path / "results"),
            ]
        )
        assert rc == 0
