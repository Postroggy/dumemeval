"""测试：LLM judge 重试（瞬时错误退避，鉴权错误不重试）。"""

from __future__ import annotations

import pytest

from dumemeval.core.retry import call_with_retries, is_retryable


class TestIsRetryable:
    def test_timeout_is_retryable(self) -> None:
        assert is_retryable(TimeoutError("timed out"))
        assert is_retryable(ConnectionError("connection reset"))
        assert is_retryable(RuntimeError("429 rate limit exceeded"))
        assert is_retryable(RuntimeError("503 Service Unavailable"))
        assert is_retryable(RuntimeError("gateway overloaded"))

    def test_http_5xx_is_retryable(self) -> None:
        assert is_retryable(RuntimeError("500 Internal Server Error"))
        assert is_retryable(RuntimeError("HTTP 502 Bad Gateway"))
        err_500 = RuntimeError("boom")
        err_500.response = type("R", (), {"status_code": 500})()  # type: ignore[attr-defined]
        assert is_retryable(err_500)
        err_401 = RuntimeError("boom")
        err_401.response = type("R", (), {"status_code": 401})()  # type: ignore[attr-defined]
        assert not is_retryable(err_401)

    def test_requests_connection_error_name_is_retryable(self) -> None:
        class ConnectionError(Exception):
            pass

        assert is_retryable(ConnectionError("Max retries exceeded"))

    def test_auth_error_is_not_retryable(self) -> None:
        assert not is_retryable(RuntimeError("401 invalid api key"))
        assert not is_retryable(ValueError("Missing API key: set OPENAI_API_KEY"))
        assert not is_retryable(RuntimeError("model does not exist"))


class TestCallWithRetries:
    def test_succeeds_after_transient_failures(self) -> None:
        calls = {"n": 0}

        def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("timeout")
            return "ok"

        sleeps: list[float] = []
        assert call_with_retries(flaky, max_retries=3, sleep_fn=sleeps.append) == "ok"
        assert calls["n"] == 3
        assert sleeps == [0.5, 1.0]

    def test_gives_up_after_max_retries(self) -> None:
        def always_fail() -> str:
            raise TimeoutError("still down")

        with pytest.raises(TimeoutError, match="still down"):
            call_with_retries(always_fail, max_retries=2, sleep_fn=lambda _: None)

    def test_does_not_retry_auth_errors(self) -> None:
        calls = {"n": 0}

        def auth_fail() -> str:
            calls["n"] += 1
            raise RuntimeError("401 invalid api key")

        with pytest.raises(RuntimeError, match="401"):
            call_with_retries(auth_fail, max_retries=5, sleep_fn=lambda _: None)
        assert calls["n"] == 1
