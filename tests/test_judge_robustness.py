"""测试：LLM judge 多次运行取多数、瞬时失败跳过、判分输入留存。"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from dumemeval.verifier import LLMJudgeVerifier


def _judge(config: dict[str, Any] | None = None) -> LLMJudgeVerifier:
    cfg = {"prompt": "memory_qa", "model": "test-model", **(config or {})}
    return LLMJudgeVerifier(cfg)


class TestNumRunsMajority:
    def test_majority_vote_picks_correct(self) -> None:
        """num_runs=3 时 2 CORRECT / 1 WRONG → CORRECT，score 为均值。"""
        v = _judge({"num_runs": 3})
        raws = iter(
            [
                '{"label": "CORRECT", "score": 1.0, "reason": "a"}',
                '{"label": "WRONG", "score": 0.0, "reason": "b"}',
                '{"label": "CORRECT", "score": 1.0, "reason": "c"}',
            ]
        )
        with patch.object(v, "_raw_judge", side_effect=lambda *_a, **_k: next(raws)):
            verdict = v.verify("alice likes latte", "latte", question="drink?")
        assert verdict.label == "CORRECT"
        assert verdict.score == pytest.approx(2 / 3)
        assert verdict.runs == 3
        assert len(verdict.run_scores) == 3

    def test_single_run_is_default(self) -> None:
        v = _judge()
        with patch.object(v, "_raw_judge", return_value='{"label": "WRONG"}'):
            verdict = v.verify("tea", "latte", question="drink?")
        assert verdict.label == "WRONG"
        assert verdict.score == 0.0
        assert verdict.runs == 1


class TestSkipFailedJudge:
    def test_skip_failed_returns_skipped_verdict(self) -> None:
        """瞬时错误 + skip_failed=True → SKIPPED（score=0），不抛。"""
        v = _judge({"skip_failed": True, "max_retries": 0})
        with patch.object(v, "_raw_judge", side_effect=TimeoutError("judge down")):
            verdict = v.verify("alice likes latte", "latte", question="drink?")
        assert verdict.label == "SKIPPED"
        assert verdict.score == 0.0
        assert "judge down" in verdict.reason

    def test_failed_judge_raises_when_not_skipped(self) -> None:
        v = _judge({"skip_failed": False, "max_retries": 0})
        with (
            patch.object(v, "_raw_judge", side_effect=TimeoutError("judge down")),
            pytest.raises(TimeoutError, match="judge down"),
        ):
            v.verify("alice likes latte", "latte", question="drink?")


class TestSaveModelInput:
    def test_verify_records_prompt_when_enabled(self) -> None:
        v = _judge({"save_model_input": True})
        with patch.object(v, "_raw_judge", return_value='{"label": "CORRECT"}'):
            verdict = v.verify("alice likes latte", "latte", question="what does she drink?")
        assert "what does she drink?" in (verdict.model_input or "")
        assert "alice likes latte" in (verdict.model_input or "")
        assert "latte" in (verdict.model_input or "")

    def test_verify_does_not_record_prompt_by_default(self) -> None:
        v = _judge()
        with patch.object(v, "_raw_judge", return_value='{"label": "CORRECT"}'):
            verdict = v.verify("alice likes latte", "latte", question="drink?")
        assert verdict.model_input is None
