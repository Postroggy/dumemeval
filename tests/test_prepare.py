"""测试：数据准备（下载 / 切 smoke 子集）。只测离线逻辑，不打网络。"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.datasets.prepare import slice_locomo_smoke, slice_shopping_smoke


def _locomo_item(n_sessions: int = 6) -> dict[str, Any]:
    conv: dict[str, Any] = {"speaker_a": "A", "speaker_b": "B"}
    for i in range(1, n_sessions + 1):
        conv[f"session_{i}"] = [{"speaker": "A", "dia_id": f"D{i}:1", "text": f"s{i} text"}]
    qa: list[dict[str, Any]] = []
    for cat in (1, 2, 3, 4):
        qa.append(
            {
                "question": f"q{cat}",
                "answer": f"a{cat}",
                "evidence": [f"D{cat}:1"],
                "category": cat,
            }
        )
    # cat5 的 evidence 也落在前 4 个 session 内（否则会被 n_sessions=4 过滤）
    qa.append({"question": "q5", "answer": "a5", "evidence": ["D4:1"], "category": 5})
    # 落在 session 5 的题：n_sessions=4 时应被切掉
    qa.append({"question": "q6", "answer": "a6", "evidence": ["D5:1"], "category": 1})
    return {"sample_id": "conv-test", "conversation": conv, "qa": qa}


class TestSliceLocomo:
    def test_sessions_trimmed_to_n(self) -> None:
        raw = [_locomo_item(6)]
        out = slice_locomo_smoke(raw, n_sessions=4, per_category=1)
        conv = out[0]["conversation"]
        assert "session_5" not in conv
        assert "session_4" in conv

    def test_qa_only_evidence_within_sessions(self) -> None:
        """evidence 落在保留 session 外的题被排除（否则答非所读）。"""
        raw = [_locomo_item(6)]
        out = slice_locomo_smoke(raw, n_sessions=4, per_category=1)
        assert len(out[0]["qa"]) == 5  # 5 类别各 1；D5 的题被排除

    def test_per_category_cap(self) -> None:
        item = _locomo_item(6)
        item["qa"] = [dict(q) for q in item["qa"]]
        item["qa"].append({"question": "q1b", "answer": "a1b", "evidence": ["D1:1"], "category": 1})
        out = slice_locomo_smoke([item], n_sessions=4, per_category=1)
        cats = {int(q["category"]) for q in out[0]["qa"]}
        assert cats == {1, 2, 3, 4, 5}
        assert sum(1 for q in out[0]["qa"] if q["category"] == 1) == 1  # 每类只留 1

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            slice_locomo_smoke([])


class TestSliceShopping:
    def test_trims_to_n_rounds(self) -> None:
        rows = [
            {
                "id": 0,
                "questions": ["q1", "q2", "q3"],
                "answers": [{"target_asin": "1"}, {"target_asin": "2"}, {"target_asin": "3"}],
                "category": "bundled_shopping",
            }
        ]
        out = slice_shopping_smoke(rows, n_rounds=2)
        assert len(out[0]["questions"]) == 2
        assert len(out[0]["answers"]) == 2

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            slice_shopping_smoke([])


class TestBundledSmokeFiles:
    """仓库捆绑的 data/smoke 子集与 prepare 切片逻辑同构（零下载可跑真 smoke）。"""

    def test_bundled_locomo_within_four_sessions(self) -> None:
        path = Path(__file__).parent.parent / "data" / "smoke" / "locomo_smoke.json"
        assert path.exists(), "捆绑 smoke 数据缺失"
        data = json.loads(path.read_text())
        assert data, "locomo_smoke 不应为空"
        conv = data[0]["conversation"]
        sessions = [
            int(k.split("_")[1]) for k in conv if k.startswith("session_") and not k.endswith("_date_time")
        ]
        assert sessions, "locomo_smoke 应含 session 对话"
        assert max(sessions) <= 4
        assert data[0]["qa"], "locomo_smoke 应含 QA"

    def test_bundled_shopping_two_rounds(self) -> None:
        path = Path(__file__).parent.parent / "data" / "smoke" / "shopping_smoke.jsonl"
        assert path.exists(), "捆绑 shopping smoke 缺失"
        row = json.loads(path.read_text().splitlines()[0])
        assert len(row["questions"]) == 2
        assert len(row["answers"]) == 2


class TestCmdPrepare:
    """``dumemeval prepare`` CLI（下载函数 monkeypatch，不打网络）。"""

    def test_all_calls_both(self, monkeypatch: Any) -> None:
        from dumemeval.cli import main

        called: list[str] = []

        def fake_locomo(**kwargs: Any) -> dict[str, Path]:
            called.append("locomo")
            return {"full": Path("/tmp/f"), "smoke": Path("/tmp/s")}

        def fake_shopping(**kwargs: Any) -> dict[str, Path]:
            called.append("shopping")
            return {"full": Path("/tmp/f"), "smoke": Path("/tmp/s")}

        monkeypatch.setattr("dumemeval.cli.prepare.prep.prepare_locomo", fake_locomo)
        monkeypatch.setattr("dumemeval.cli.prepare.prep.prepare_shopping", fake_shopping)
        rc = main(["prepare"])
        assert rc == 0
        assert called == ["locomo", "shopping"]

    def test_dataset_choice(self, monkeypatch: Any) -> None:
        from dumemeval.cli import main

        called: list[str] = []

        def fake_shopping(**kwargs: Any) -> dict[str, Path]:
            called.append("shopping")
            return {"full": Path("/tmp/f"), "smoke": Path("/tmp/s")}

        monkeypatch.setattr("dumemeval.cli.prepare.prep.prepare_shopping", fake_shopping)
        rc = main(["prepare", "--dataset", "shopping", "--root", "/tmp/x"])
        assert rc == 0
        assert called == ["shopping"]

    def test_unknown_dataset_rejected(self) -> None:
        from dumemeval.cli import build_parser

        with pytest.raises(SystemExit):
            build_parser().parse_args(["prepare", "--dataset", "bogus"])
