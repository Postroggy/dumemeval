"""测试：Verifier 判分体系。"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.verifier import LLMJudgeVerifier, RuleVerifier, VerifierFactory
from dumemeval.verifier.parsers import parse, parse_search_grader, parse_yes_no


class TestRuleVerifier:
    def test_substring_match(self) -> None:
        v = RuleVerifier({"mode": "substring"})
        r = v.verify("Alice prefers latte without sugar", "latte")
        assert r.is_pass and r.label == "CORRECT"

    def test_substring_no_match(self) -> None:
        v = RuleVerifier({"mode": "substring"})
        r = v.verify("Alice prefers tea", "latte")
        assert not r.is_pass and r.label == "WRONG"

    def test_exact_match(self) -> None:
        v = RuleVerifier({"mode": "exact"})
        assert v.verify("latte", "latte").is_pass
        # 默认大小写不敏感：Latte == latte
        assert v.verify("Latte", "latte").is_pass

    def test_exact_case_sensitive(self) -> None:
        v = RuleVerifier({"mode": "exact", "case_sensitive": True})
        assert not v.verify("Latte", "latte").is_pass

    def test_regex_match(self) -> None:
        v = RuleVerifier({"mode": "regex"})
        assert v.verify("Alice likes latte", r"likes \w+").is_pass

    def test_case_insensitive(self) -> None:
        v = RuleVerifier({"mode": "substring", "case_sensitive": False})
        assert v.verify("ALICE LIKES LATTE", "latte").is_pass


class TestLLMJudgeVerifier:
    def test_parse_json_label(self) -> None:
        r = parse('The answer matches. {"label": "CORRECT"}')
        assert r.label == "CORRECT" and r.score == 1.0

    def test_parse_json_score(self) -> None:
        r = parse('{"score": 0.5, "reason": "partial"}')
        assert r.score == 0.5 and r.is_pass

    def test_parse_bare_label(self) -> None:
        assert parse("The answer is wrong. WRONG").label == "WRONG"

    def test_parse_unknown(self) -> None:
        r = parse("unparseable output")
        assert r.label == "UNKNOWN"

    def test_unknown_prompt_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown judge prompt"):
            LLMJudgeVerifier({"prompt": "nope"})


class TestVerifierFactory:
    def test_create_rule(self) -> None:
        assert isinstance(VerifierFactory.create({"type": "rule"}), RuleVerifier)

    def test_create_llm(self) -> None:
        assert isinstance(
            VerifierFactory.create({"type": "llm_judge", "prompt": "memory_qa"}), LLMJudgeVerifier
        )

    def test_default_is_rule(self) -> None:
        assert isinstance(VerifierFactory.create(None), RuleVerifier)

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown verifier type"):
            VerifierFactory.create({"type": "nope"})


class TestResponsesFallback:
    def test_unsupported_returns_true(self) -> None:
        """API 不支持类错误 → 可回退。"""

        class UnsupportedEndpoint(RuntimeError):
            response = SimpleNamespace(status_code=404)

        for text in ("404: endpoint not found", "Unknown endpoint: /v1/responses"):
            error = UnsupportedEndpoint(text)
            assert LLMJudgeVerifier._is_responses_unsupported(error)
        assert not LLMJudgeVerifier._is_responses_unsupported(Exception("Unknown endpoint: /v1/responses"))

    def test_auth_error_returns_false(self) -> None:
        """鉴权/模型错误 → 不可回退（应抛出）。"""
        assert not LLMJudgeVerifier._is_responses_unsupported(Exception("401: invalid api key"))
        assert not LLMJudgeVerifier._is_responses_unsupported(Exception("Model 'gpt-5' does not exist"))
        assert not LLMJudgeVerifier._is_responses_unsupported(Exception("Connection timeout"))


class TestMathEquivalencePrompt:
    """math_equivalence：官方 math_env.judge 只回答 yes/no，无 JSON/label。"""

    def test_prompt_registered(self) -> None:
        v = LLMJudgeVerifier({"prompt": "math_equivalence"})
        assert v.prompt_name == "math_equivalence"

    def test_parse_yes(self) -> None:
        r = parse_yes_no("Yes, these are equivalent.")
        assert r.is_pass and r.score == 1.0

    def test_parse_no(self) -> None:
        r = parse_yes_no("No, they differ by a sign.")
        assert not r.is_pass and r.score == 0.0

    def test_build_prompt_uses_query_and_ground_truth(self) -> None:
        v = LLMJudgeVerifier({"prompt": "math_equivalence"})
        _, user_prompt = v._build_prompts("my answer", "gold answer", {"question": "what is x?"})
        assert "what is x?" in user_prompt
        assert "my answer" in user_prompt
        assert "gold answer" in user_prompt


class TestSearchGraderPrompt:
    """search_grader：官方 GRADER_TEMPLATE，correct: yes/no + confidence。"""

    def test_prompt_registered(self) -> None:
        v = LLMJudgeVerifier({"prompt": "search_grader"})
        assert v.prompt_name == "search_grader"

    def test_parse_correct(self) -> None:
        r = parse_search_grader("extracted_final_answer: Sonia\ncorrect: yes\nconfidence: 90")
        assert r.is_pass and r.score == 1.0

    def test_parse_incorrect(self) -> None:
        r = parse_search_grader("extracted_final_answer: None\ncorrect: no\nconfidence: 100")
        assert not r.is_pass and r.score == 0.0
