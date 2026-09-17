"""测试：ReportGenerator。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.core.config import ExperimentConfig
from dumemeval.models import (
    GitSnapshot,
    MetricReport,
    QualityResult,
    RunProvenance,
    TaskExecution,
    TaskResult,
    UtilityResult,
)
from dumemeval.report import ReportGenerator


def _make_result() -> TaskResult:
    return TaskResult(
        task_id="test-task",
        task_name="test-task",
        execution=TaskExecution(task_id="test-task", task_name="test-task", memory_backend="test-mem"),
        metrics=MetricReport(
            quality=QualityResult(precision=0.8, recall=0.6),
            utility=UtilityResult(task_success=True, success_rate=1.0, turns=2),
        ),
    )


def _cfg() -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "experiment": {"name": "e", "protocol": "memory_session_transfer", "version": "1.0"},
            "agent": {"runtime": "hermes", "model": "m1"},
            "memory": {"name": "m", "type": "hermes_builtin"},
            "task": {"sessions": [{"instruction": "s1"}, {"instruction": "s2"}]},
        }
    )


class TestReportGenerator:
    def test_generate_creates_files(self, tmp_path: Path) -> None:
        gen = ReportGenerator(output_dir=tmp_path)
        run_dir = gen.generate(_make_result())
        assert (run_dir / "result.json").exists()
        assert (run_dir / "report.md").exists()

    def test_generate_respects_json_only(self, tmp_path: Path) -> None:
        gen = ReportGenerator(output_dir=tmp_path)
        run_dir = gen.generate(_make_result(), formats="json")
        assert (run_dir / "result.json").exists()
        assert not (run_dir / "report.md").exists()

    def test_generate_json_content(self, tmp_path: Path) -> None:
        gen = ReportGenerator(output_dir=tmp_path)
        run_dir = gen.generate(_make_result())
        data = json.loads((run_dir / "result.json").read_text())
        assert data["task_name"] == "test-task"
        assert data["execution"]["memory_backend"] == "test-mem"
        assert data["metrics"]["quality"]["precision"] == 0.8
        assert data["metrics"]["utility"]["task_success"] is True

    def test_generate_md_content(self, tmp_path: Path) -> None:
        gen = ReportGenerator(output_dir=tmp_path)
        run_dir = gen.generate(_make_result())
        md = (run_dir / "report.md").read_text()
        assert "# test-task — test-mem" in md
        assert "precision: 0.800" in md
        assert "success_rate: 1.000" in md

    def test_md_has_meta_and_no_dup_metrics(self, tmp_path: Path) -> None:
        """元信息头（协议/agent/memory）+ 去掉与后四段重复的扁平 Metrics 段。"""
        run_dir = ReportGenerator(tmp_path).generate(_make_result(), _cfg())
        md = (run_dir / "report.md").read_text()
        head = md.splitlines()[2]
        assert "memory_session_transfer" in head and "hermes" in head and "hermes_builtin" in head
        assert "## Metrics（聚合）" not in md

    def test_directory_naming(self, tmp_path: Path) -> None:
        gen = ReportGenerator(output_dir=tmp_path)
        run_dir = gen.generate(_make_result())
        assert run_dir.name == "test-task__test-mem"

    def test_mock_banner_and_reproduce_block(self, tmp_path: Path) -> None:
        """mock 必须在报告正文声明不可引用；并给出复现命令 + git 段。"""
        provenance = RunProvenance(
            mock=True,
            reproduce=".venv/bin/python -m dumemeval run --config configs/e.yaml --output results --mock",
            git=GitSnapshot(commit="abc1234", branch="main", dirty=False),
            judging_type="llm_judge",
            judging_model="gpt-4o-mini",
            judging_num_runs=3,
            judging_skip_failed=True,
        )
        md = (
            ReportGenerator(tmp_path).generate(_make_result(), _cfg(), provenance=provenance) / "report.md"
        ).read_text()
        assert "mock" in md.lower()
        assert "不代表 agent 真实水平" in md or "不可引用" in md
        assert "```bash" in md and "dumemeval run" in md
        assert "abc1234" in md
        assert "num_runs" in md and "3" in md

    def test_skipped_and_std_in_quality_section(self, tmp_path: Path) -> None:
        result = _make_result()
        assert result.metrics is not None
        result.metrics.quality = QualityResult(
            precision=0.5,
            recall=0.5,
            details=[
                {
                    "fact": "a",
                    "in_memory": True,
                    "score": 1.0,
                    "label": "CORRECT",
                    "runs": 3,
                    "score_std": 0.0,
                },
                {
                    "fact": "b",
                    "in_memory": False,
                    "score": 0.0,
                    "label": "SKIPPED",
                    "runs": 1,
                    "score_std": 0.0,
                },
            ],
        )
        md = (ReportGenerator(tmp_path).generate(result) / "report.md").read_text()
        assert "SKIPPED" in md
        assert "1/2" in md or "skipped=1" in md.lower() or "1 skipped" in md.lower()
