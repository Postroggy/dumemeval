"""测试：judging 配置透传到 benchmark LLMJudgeVerifier。"""

from __future__ import annotations

from dumemeval.verifier import llm_judge_config, make_llm_judge


def test_llm_judge_config_keeps_prompt_and_passthrough() -> None:
    cfg = llm_judge_config(
        "memory_qa",
        {"model": "DeepSeek-V4-Flash", "num_runs": 3, "prompt": "task_success", "type": "llm_judge"},
    )
    assert cfg["prompt"] == "memory_qa"
    assert cfg["model"] == "DeepSeek-V4-Flash"
    assert cfg["num_runs"] == 3
    assert "type" not in cfg


def test_make_llm_judge_applies_model() -> None:
    v = make_llm_judge("search_grader", {"model": "custom-judge", "max_tokens": 256})
    assert v.prompt_name == "search_grader"
    assert v.model == "custom-judge"
    assert v.max_tokens == 256
