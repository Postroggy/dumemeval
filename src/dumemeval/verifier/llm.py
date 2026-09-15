"""LLM judge 判分器（支持 OpenAI / Anthropic 双 provider）。

设计要点：
- Responses API 优先，退 chat completions（仅对"API 不支持"类错误回退）
- base_url 自动补 /v1（网关兼容）
- reasoning_content fallback（DeepSeek 推理模型）
- num_runs 多数票 / 明确限流拒绝重试 / skip_failed / save_model_input
"""

from __future__ import annotations

import os
from typing import Any, ClassVar

from .base import BaseVerifier, Verdict
from .clients import AnthropicJudgeClient, OpenAIJudgeClient, is_responses_unsupported
from .parsers import parse, parse_search_grader, parse_yes_no
from .retry import aggregate_verdicts, call_with_retries


class LLMJudgeVerifier(BaseVerifier):
    """LLM judge 判分器，支持 OpenAI / Anthropic 双 provider。

    config:
        prompt / model / provider / api_key_env / base_url / temperature / max_tokens
        num_runs: 重复次数（多数票 + 分数均值，默认 1）
        max_retries: 明确 429 拒绝最多尝试次数（含首次，默认 3）；送达不确定时不重试
        skip_failed: 失败记 SKIPPED 而非抛出
        save_model_input: 把 user prompt 写入 Verdict.model_input
    """

    name = "llm_judge"
    # LLMJudgeVerifier 接受的全部 config 键——``llm_judge_config`` 据此做透传，
    # 加字段只改这一处，不需要在 metrics 侧再维护一份清单。
    _CONFIG_KEYS: ClassVar[tuple[str, ...]] = (
        "prompt",
        "model",
        "base_url",
        "provider",
        "api_key_env",
        "temperature",
        "max_tokens",
        "num_runs",
        "max_retries",
        "skip_failed",
        "save_model_input",
    )
    _PROMPT_TEMPLATES: ClassVar[dict[str, tuple[str, str]]] = {
        "memory_qa": ("MEMORY_QA_JUDGE_SYSTEM", "MEMORY_QA_JUDGE_PROMPT"),
        "memory_quality": ("MEMORY_QUALITY_JUDGE_SYSTEM", "MEMORY_QUALITY_JUDGE_PROMPT"),
        "task_success": ("TASK_SUCCESS_JUDGE_SYSTEM", "TASK_SUCCESS_JUDGE_PROMPT"),
        "math_equivalence": ("MATH_EQUIVALENCE_JUDGE_SYSTEM", "MATH_EQUIVALENCE_JUDGE_PROMPT"),
        "search_grader": ("SEARCH_GRADER_JUDGE_SYSTEM", "SEARCH_GRADER_JUDGE_PROMPT"),
    }
    _ANTHROPIC_HINTS = ("anthropic", "claude")
    _is_responses_unsupported = staticmethod(is_responses_unsupported)

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.prompt_name = self.config.get("prompt", "memory_qa")
        if self.prompt_name not in self._PROMPT_TEMPLATES:
            raise ValueError(
                f"Unknown judge prompt: {self.prompt_name!r}. Supported: {list(self._PROMPT_TEMPLATES)}"
            )
        # judge 模型兜底 gpt-4o-mini：仅为「忘配也能跑」的兜底，正式评测应显式
        # 配置 judging.model（judge 选型直接影响分数可信度，见 GOVERNANCE）
        self.model = self.config.get("model") or os.environ.get("JUDGE_MODEL") or "gpt-4o-mini"
        self.base_url = self.config.get("base_url") or os.environ.get("JUDGE_BASE_URL")
        self.provider = self._resolve_provider()
        self.temperature = float(self.config.get("temperature", 0))
        self.max_tokens = int(self.config.get("max_tokens", 512))
        self.num_runs = max(1, int(self.config.get("num_runs", 1)))
        self.max_retries = max(0, int(self.config.get("max_retries", 3)))
        self.skip_failed = bool(self.config.get("skip_failed", False))
        self.save_model_input = bool(self.config.get("save_model_input", False))
        self._client: OpenAIJudgeClient | AnthropicJudgeClient | None = None

    def _resolve_provider(self) -> str:
        explicit = self.config.get("provider")
        if explicit:
            if explicit not in ("openai", "anthropic"):
                raise ValueError(f"Unknown provider: {explicit!r}. Use 'openai' or 'anthropic'.")
            return str(explicit)
        api_key_env = self.config.get("api_key_env", "")
        if api_key_env.startswith("ANTHROPIC_"):
            return "anthropic"
        if self.base_url and any(hint in self.base_url.lower() for hint in self._ANTHROPIC_HINTS):
            return "anthropic"
        return "openai"

    def _get_client(self) -> OpenAIJudgeClient | AnthropicJudgeClient:
        if self._client is not None:
            return self._client
        if self.provider == "anthropic":
            env_name = self.config.get("api_key_env", "ANTHROPIC_API_KEY")
            api_key = os.environ.get(env_name)
            if not api_key:
                raise ValueError(f"Missing API key: set {env_name}")
            self._client = AnthropicJudgeClient(api_key, self.base_url)
        else:
            env_name = (
                self.config.get("api_key_env") or os.environ.get("JUDGE_API_KEY_ENV") or "OPENAI_API_KEY"
            )
            api_key = os.environ.get(env_name)
            if not api_key:
                raise ValueError(f"Missing API key: set {env_name}")
            self._client = OpenAIJudgeClient(api_key, self.base_url)
        return self._client

    def _build_prompts(self, response: str, ground_truth: str, ctx: dict[str, Any]) -> tuple[str, str]:
        from . import prompts as prompt_mod

        sys_name, template_name = self._PROMPT_TEMPLATES[self.prompt_name]
        sys_prompt = getattr(prompt_mod, sys_name)
        template = getattr(prompt_mod, template_name)
        if self.prompt_name == "memory_qa":
            user_prompt = template.format(
                question=ctx.get("question", ""), golden_answer=ground_truth, response=response
            )
        elif self.prompt_name == "memory_quality":
            user_prompt = template.format(memory_content=response, fact=ground_truth)
        elif self.prompt_name in ("math_equivalence", "search_grader"):
            user_prompt = template.format(
                question=ctx.get("question", ""), golden_answer=ground_truth, response=response
            )
        else:
            user_prompt = template.format(task=ctx.get("task", ""), rubric=ground_truth, response=response)
        return sys_prompt, user_prompt

    def verify(self, response: str, ground_truth: str, **ctx: Any) -> Verdict:
        system_prompt, user_prompt = self._build_prompts(response, ground_truth, ctx)
        try:
            verdicts: list[Verdict] = []
            for _ in range(self.num_runs):
                raw = call_with_retries(
                    lambda: self._raw_judge(system_prompt, user_prompt),
                    max_retries=self.max_retries,
                )
                verdicts.append(self._parse_raw(raw))
            verdict = aggregate_verdicts(verdicts) if len(verdicts) > 1 else verdicts[0]
        except Exception as exc:
            if self.skip_failed:
                return Verdict(
                    label="SKIPPED",
                    score=0.0,
                    reason=str(exc),
                    model_input=user_prompt if self.save_model_input else None,
                )
            raise
        if self.save_model_input:
            verdict.model_input = user_prompt
        return verdict

    def _parse_raw(self, raw: str) -> Verdict:
        if self.prompt_name == "math_equivalence":
            return parse_yes_no(raw)
        if self.prompt_name == "search_grader":
            return parse_search_grader(raw)
        return parse(raw)

    def verify_with_prompt(self, user_prompt: str, system_prompt: str = "") -> Verdict:
        """用任意 prompt 调 judge（供数据集自定义 judge 模板使用）。"""
        system = system_prompt or "You are an expert evaluator."
        try:
            raw = call_with_retries(
                lambda: self._raw_judge(system, user_prompt),
                max_retries=self.max_retries,
            )
        except Exception as exc:
            if self.skip_failed:
                return Verdict(
                    label="SKIPPED",
                    score=0.0,
                    reason=str(exc),
                    model_input=user_prompt if self.save_model_input else None,
                )
            raise
        return Verdict(
            label="",
            score=0.0,
            reason=raw[:200],
            raw=raw,
            model_input=user_prompt if self.save_model_input else None,
        )

    def _raw_judge(self, system_prompt: str, user_prompt: str) -> str:
        return self._get_client().complete(
            self.model, system_prompt, user_prompt, self.temperature, self.max_tokens
        )


# ── 计算器接入工厂 ────────────────────────────────────────────────────────────
# 把 ``ExperimentConfig.judging`` 接到各 benchmark 计算器的 LLMJudgeVerifier。
# 计算器自己的 prompt（memory_qa / search_grader / math_equivalence …）始终覆盖
# 配置里的 ``judging.prompt``——那是 Quality 默认，不是数据集口径。
# 其余字段（model / key / 多数票 / 重试）透传，避免计算器各自 ``LLMJudgeVerifier({"prompt": ...})``
# 静默丢掉用户配置的 judge 模型。
# 透传字段直接取自 ``LLMJudgeVerifier._CONFIG_KEYS``（type / prompt 不透传），不重复维护清单。

# JudgeSpec 里真正影响 LLMJudgeVerifier 行为的字段（type / prompt 不透传）
_PASSTHROUGH = tuple(key for key in LLMJudgeVerifier._CONFIG_KEYS if key != "prompt")


def llm_judge_config(prompt: str, llm_config: dict[str, Any] | None) -> dict[str, Any]:
    """合并用户 judging 配置与计算器自己的 prompt。"""
    cfg: dict[str, Any] = {}
    if llm_config:
        for key in _PASSTHROUGH:
            value = llm_config.get(key)
            if value is not None:
                cfg[key] = value
    cfg["prompt"] = prompt
    return cfg


def make_llm_judge(prompt: str, llm_config: dict[str, Any] | None = None) -> LLMJudgeVerifier:
    """构造 LLMJudgeVerifier：prompt 由计算器决定，其余来自 judging 配置。"""
    return LLMJudgeVerifier(llm_judge_config(prompt, llm_config))
