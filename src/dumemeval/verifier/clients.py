"""Judge LLM 客户端（OpenAI / Anthropic），从 LLMJudgeVerifier 拆出。"""

from __future__ import annotations

import logging
from typing import Any


def is_responses_unsupported(exc: Exception) -> bool:
    """仅对明确的 Responses API 不支持类错误回退；鉴权等真错误返回 False。"""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if status not in (400, 404, 405, 422, 501):
        return False
    msg = str(exc).lower()
    if any(marker in msg for marker in ("not implemented", "unsupported", "not support")):
        return True
    endpoint_markers = ("endpoint", "path", "route", "resource", "/responses")
    if any(marker in msg for marker in endpoint_markers) and any(
        marker in msg for marker in ("not found", "no such", "unknown", "404", "405")
    ):
        return True
    return "responses" in msg and any(
        marker in msg for marker in ("invalid request", "convert_request_failed")
    )


def normalize_openai_base_url(base_url: str) -> str:
    """确保 OpenAI SDK 能正确拼接 /chat/completions。"""
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    return url


class OpenAIJudgeClient:
    """OpenAI 兼容 judge：Responses API 优先，退 chat completions。"""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "LLMJudgeVerifier (openai provider) requires `openai` package. Install with: pip install openai"
            ) from e
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 0}
        if base_url:
            kwargs["base_url"] = normalize_openai_base_url(base_url)
        self._client: Any = OpenAI(**kwargs)
        self._logger = logging.getLogger(__name__)

    def complete(
        self, model: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if hasattr(self._client, "responses"):
            try:
                resp = self._client.responses.create(
                    model=model,
                    input=messages,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                )
                return str(resp.output_text or "")
            except Exception as e:
                if is_responses_unsupported(e):
                    self._logger.debug("Responses API 不可用（%s），回退 chat completions", e)
                else:
                    raise
        completion = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        message = completion.choices[0].message
        content = message.content or ""
        if not content:
            content = getattr(message, "reasoning_content", "") or ""
        return str(content)


class AnthropicJudgeClient:
    """Anthropic messages API judge。"""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ImportError(
                "LLMJudgeVerifier (anthropic provider) requires `anthropic` package. "
                "Install with: pip install anthropic"
            ) from e
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 0}
        if base_url:
            kwargs["base_url"] = base_url
        self._client: Any = Anthropic(**kwargs)

    def complete(
        self, model: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int
    ) -> str:
        resp = self._client.messages.create(
            model=model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=max_tokens,
        )
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
