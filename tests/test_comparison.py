"""测试：跨 run 比较（业务问题：接 memory vs 不接 / 多 backend 横评）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dumemeval.comparison import compare_runs, load_run
from dumemeval.models import MetricDirection


def _write_run(
    root: Path,
    name: str,
    *,
    metrics: dict[str, float],
    benchmark: str | None = "locomo",
    n_tasks: int = 2,
    mock: bool = False,
    judge_model: str = "gpt-4o-mini",
    judge_num_runs: int = 1,
) -> Path:
    run = root / name
    run.mkdir(parents=True, exist_ok=True)
    summary = {
        "experiment_name": name,
        "generated_at": "2026-08-28 10:00:00",
        "n_tasks": n_tasks,
        "n_concurrent": 1,
        "mock": mock,
        "utility_success_rate_avg": metrics.get("utility.success_rate", 0.0),
        "benchmark": (
            {"name": benchmark, "values": {"f1": metrics.get("locomo.f1", 0.0)}} if benchmark else None
        ),
        "per_task": [],
        "warnings": [],
        "metrics": metrics,
    }
    (run / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    (run / "experiment_config.json").write_text(
        json.dumps(
            {
                "provenance": {
                    "mock": mock,
                    "reproduce": f"run {name}",
                    "git": {"commit": "abc1234", "branch": "main", "dirty": False},
                    "judging_type": "llm_judge",
                    "judging_model": judge_model,
                    "judging_num_runs": judge_num_runs,
                    "judging_skip_failed": False,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return run


class TestLoadRun:
    def test_loads_summary_and_provenance(self, tmp_path: Path) -> None:
        run = _write_run(tmp_path, "base", metrics={"utility.success_rate": 0.6})
        ref = load_run(run)
        assert ref.label == "base"
        assert ref.summary.n_tasks == 2
        assert ref.provenance is not None
        assert ref.provenance.judging_model == "gpt-4o-mini"

    def test_missing_summary_raises(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        with pytest.raises(FileNotFoundError, match=r"summary\.json"):
            load_run(tmp_path / "empty")


class TestCompareTwoArms:
    """业务问题 1：接 memory vs 不接 memory。"""

    def test_delta_against_baseline(self, tmp_path: Path) -> None:
        base = _write_run(tmp_path, "base", metrics={"utility.success_rate": 0.6, "locomo.f1": 0.412})
        mem = _write_run(tmp_path, "mem", metrics={"utility.success_rate": 0.8, "locomo.f1": 0.583})
        cmp_result = compare_runs([load_run(base), load_run(mem)], baseline="base")

        assert cmp_result.baseline == "base"
        assert cmp_result.labels == ["base", "mem"]
        f1 = cmp_result.delta_for("locomo.f1")
        assert f1 is not None
        assert f1.values["base"] == pytest.approx(0.412)
        assert f1.values["mem"] == pytest.approx(0.583)
        assert f1.delta("mem") == pytest.approx(0.171)
        assert f1.improved("mem") is True

    def test_lower_is_better_metrics_flip_improvement(self, tmp_path: Path) -> None:
        base = _write_run(tmp_path, "base", metrics={"efficiency.cost_usd": 0.81})
        mem = _write_run(tmp_path, "mem", metrics={"efficiency.cost_usd": 1.24})
        cmp_result = compare_runs([load_run(base), load_run(mem)], baseline="base")

        cost = cmp_result.delta_for("efficiency.cost_usd")
        assert cost is not None
        assert cost.direction == MetricDirection.LOWER_IS_BETTER
        assert cost.delta("mem") == pytest.approx(0.43)
        assert cost.improved("mem") is False  # 更贵 = 变差

    def test_missing_metric_in_one_arm_is_none(self, tmp_path: Path) -> None:
        base = _write_run(tmp_path, "base", metrics={"utility.success_rate": 0.6})
        mem = _write_run(tmp_path, "mem", metrics={"utility.success_rate": 0.8, "quality.recall": 0.5})
        cmp_result = compare_runs([load_run(base), load_run(mem)], baseline="base")

        recall = cmp_result.delta_for("quality.recall")
        assert recall is not None
        assert recall.values.get("base") is None
        assert recall.delta("mem") is None  # 无基线值 → 不编造 delta


class TestLeaderboard:
    """业务问题 2：多 backend 横评（不指定 baseline）。"""

    def test_no_baseline_still_ranks(self, tmp_path: Path) -> None:
        refs = [
            load_run(_write_run(tmp_path, "everos", metrics={"locomo.f1": 0.58})),
            load_run(_write_run(tmp_path, "mem0", metrics={"locomo.f1": 0.41})),
            load_run(_write_run(tmp_path, "none", metrics={"locomo.f1": 0.20})),
        ]
        cmp_result = compare_runs(refs)
        assert cmp_result.baseline is None
        f1 = cmp_result.delta_for("locomo.f1")
        assert f1 is not None
        assert f1.best_label() == "everos"
        assert f1.delta("mem0") is None  # 无 baseline → 无 delta

    def test_lower_is_better_best_is_min(self, tmp_path: Path) -> None:
        refs = [
            load_run(_write_run(tmp_path, "a", metrics={"efficiency.cost_usd": 2.0})),
            load_run(_write_run(tmp_path, "b", metrics={"efficiency.cost_usd": 0.5})),
        ]
        cmp_result = compare_runs(refs)
        cost = cmp_result.delta_for("efficiency.cost_usd")
        assert cost is not None
        assert cost.best_label() == "b"


class TestComparabilityWarnings:
    """可信：控制变量不一致必须显式警告，而不是静默出表。"""

    def test_mock_run_makes_table_unciteable(self, tmp_path: Path) -> None:
        base = _write_run(tmp_path, "base", metrics={"locomo.f1": 0.4}, mock=True)
        mem = _write_run(tmp_path, "mem", metrics={"locomo.f1": 0.6})
        cmp_result = compare_runs([load_run(base), load_run(mem)], baseline="base")
        assert cmp_result.has_mock is True
        assert any("mock" in w.lower() for w in cmp_result.warnings)

    def test_different_benchmark_warns(self, tmp_path: Path) -> None:
        a = _write_run(tmp_path, "a", metrics={"locomo.f1": 0.4}, benchmark="locomo")
        b = _write_run(tmp_path, "b", metrics={"locomo.f1": 0.6}, benchmark="longmemeval")
        cmp_result = compare_runs([load_run(a), load_run(b)])
        assert any("benchmark" in w for w in cmp_result.warnings)

    def test_different_judge_model_warns(self, tmp_path: Path) -> None:
        a = _write_run(tmp_path, "a", metrics={"locomo.f1": 0.4}, judge_model="gpt-4o-mini")
        b = _write_run(tmp_path, "b", metrics={"locomo.f1": 0.6}, judge_model="deepseek")
        cmp_result = compare_runs([load_run(a), load_run(b)])
        assert any("judge" in w.lower() for w in cmp_result.warnings)

    def test_different_task_count_warns(self, tmp_path: Path) -> None:
        a = _write_run(tmp_path, "a", metrics={"locomo.f1": 0.4}, n_tasks=2)
        b = _write_run(tmp_path, "b", metrics={"locomo.f1": 0.6}, n_tasks=5)
        cmp_result = compare_runs([load_run(a), load_run(b)])
        assert any("task" in w.lower() for w in cmp_result.warnings)

    def test_aligned_runs_have_no_warnings(self, tmp_path: Path) -> None:
        a = _write_run(tmp_path, "a", metrics={"locomo.f1": 0.4})
        b = _write_run(tmp_path, "b", metrics={"locomo.f1": 0.6})
        refs = [load_run(a), load_run(b)]
        for ref in refs:
            assert ref.provenance is not None
            ref.provenance.controls = dict.fromkeys(
                ("tasks", "dataset", "agent", "judge", "runtime", "task_environment", "code"), "same-fixture"
            )
        cmp_result = compare_runs(refs)
        assert cmp_result.warnings == []

    def test_legacy_runs_without_fingerprints_are_unverified(self, tmp_path: Path) -> None:
        a = _write_run(tmp_path, "a", metrics={"locomo.f1": 0.4})
        b = _write_run(tmp_path, "b", metrics={"locomo.f1": 0.6})
        warnings = compare_runs([load_run(a), load_run(b)]).warnings
        assert any("fingerprints are missing" in warning for warning in warnings)


class TestGuards:
    def test_single_run_rejected(self, tmp_path: Path) -> None:
        only = load_run(_write_run(tmp_path, "solo", metrics={"locomo.f1": 0.4}))
        with pytest.raises(ValueError, match="at least 2"):
            compare_runs([only])

    def test_unknown_baseline_rejected(self, tmp_path: Path) -> None:
        refs = [
            load_run(_write_run(tmp_path, "a", metrics={"locomo.f1": 0.4})),
            load_run(_write_run(tmp_path, "b", metrics={"locomo.f1": 0.6})),
        ]
        with pytest.raises(ValueError, match="baseline"):
            compare_runs(refs, baseline="nope")

    def test_duplicate_labels_rejected(self, tmp_path: Path) -> None:
        """同一 run 传两次会让表出现同名列、Δ 恒为 0——直接拒绝。"""
        run = _write_run(tmp_path, "a", metrics={"locomo.f1": 0.4})
        with pytest.raises(ValueError, match="重复"):
            compare_runs([load_run(run), load_run(run)], baseline="a")


class TestComparisonReport:
    def test_markdown_has_delta_and_arrows(self, tmp_path: Path) -> None:
        from dumemeval.comparison_report import render_markdown

        refs = [
            load_run(_write_run(tmp_path, "base", metrics={"locomo.f1": 0.4, "efficiency.cost_usd": 0.8})),
            load_run(_write_run(tmp_path, "mem", metrics={"locomo.f1": 0.6, "efficiency.cost_usd": 1.2})),
        ]
        md = render_markdown(compare_runs(refs, baseline="base"), refs)
        assert "base（baseline）" in md
        assert "`locomo.f1`" in md
        assert "+0.2000 ↑" in md  # f1 变高 = 变好
        assert "+0.4000 ↓" in md  # cost 变高 = 变差

    def test_markdown_leaderboard_marks_best(self, tmp_path: Path) -> None:
        from dumemeval.comparison_report import render_markdown

        refs = [
            load_run(_write_run(tmp_path, "everos", metrics={"locomo.f1": 0.58})),
            load_run(_write_run(tmp_path, "mem0", metrics={"locomo.f1": 0.41})),
        ]
        md = render_markdown(compare_runs(refs), refs)
        assert "best" in md
        assert "everos" in md

    def test_mock_banner_in_markdown(self, tmp_path: Path) -> None:
        from dumemeval.comparison_report import render_markdown

        refs = [
            load_run(_write_run(tmp_path, "a", metrics={"locomo.f1": 0.4}, mock=True)),
            load_run(_write_run(tmp_path, "b", metrics={"locomo.f1": 0.6})),
        ]
        md = render_markdown(compare_runs(refs), refs)
        assert "不可引用" in md

    def test_write_comparison_files(self, tmp_path: Path) -> None:
        from dumemeval.comparison_report import write_comparison

        refs = [
            load_run(_write_run(tmp_path, "a", metrics={"locomo.f1": 0.4})),
            load_run(_write_run(tmp_path, "b", metrics={"locomo.f1": 0.6})),
        ]
        out = write_comparison(compare_runs(refs, baseline="a"), refs, tmp_path / "cmp")
        assert (out / "comparison.md").exists()
        data = json.loads((out / "comparison.json").read_text())
        assert data["baseline"] == "a"


class TestCompareCLI:
    def test_cli_compare_prints_table(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from dumemeval.cli import main

        base = _write_run(tmp_path, "base", metrics={"locomo.f1": 0.4})
        mem = _write_run(tmp_path, "mem", metrics={"locomo.f1": 0.6})
        rc = main(["compare", str(base), str(mem), "--baseline", "base"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "`locomo.f1`" in out
        assert "+0.2000" in out

    def test_cli_compare_writes_output(self, tmp_path: Path) -> None:
        from dumemeval.cli import main

        base = _write_run(tmp_path, "base", metrics={"locomo.f1": 0.4})
        mem = _write_run(tmp_path, "mem", metrics={"locomo.f1": 0.6})
        rc = main(["compare", str(base), str(mem), "--output", str(tmp_path / "cmp")])
        assert rc == 0
        assert (tmp_path / "cmp" / "comparison.md").exists()

    def test_cli_compare_reports_user_error_without_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """label 重复等用户输入问题：退出码 2 + 清晰提示，不抛 traceback。"""
        from dumemeval.cli import main

        run = _write_run(tmp_path, "same", metrics={"locomo.f1": 0.4})
        rc = main(["compare", str(run), str(run)])
        assert rc == 2
        assert "重复" in capsys.readouterr().out

    def test_cli_compare_missing_summary_is_user_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from dumemeval.cli import main

        ok = _write_run(tmp_path, "ok", metrics={"locomo.f1": 0.4})
        empty = tmp_path / "empty"
        empty.mkdir()
        rc = main(["compare", str(ok), str(empty)])
        assert rc == 2
        assert "summary.json" in capsys.readouterr().out
