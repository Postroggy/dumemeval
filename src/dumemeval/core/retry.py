"""瞬时错误重试（HTTP / LLM 共用）。

鉴权、模型不存在等真错误立即抛出；429 / 5xx / 超时 / 连接错误指数退避。
"""

from __future__ import annotations

import time
from collections.abc import Callable

_RETRYABLE_MARKERS = (
    "429",
    "rate limit",
    "500",
    "502",
    "503",
    "504",
    "overloaded",
    "timeout",
    "temporar",
    "unavailable",
    "connection reset",
    "connection aborted",
    "connection error",
)
_NON_RETRYABLE_MARKERS = (
    "401",
    "403",
    "invalid api key",
    "missing api key",
    "does not exist",
)


def is_retryable(exc: BaseException) -> bool:
    """瞬时错误可重试；鉴权 / 模型不存在等真错误不可重试。"""
    if isinstance(exc, TimeoutError | ConnectionError):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        if status in (401, 403, 404):
            return False
        if status == 429 or status >= 500:
            return True
    msg = str(exc).lower()
    if any(marker in msg for marker in _NON_RETRYABLE_MARKERS):
        return False
    if type(exc).__name__ in {"ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout"}:
        return True
    return any(marker in msg for marker in _RETRYABLE_MARKERS)


def call_with_retries[T](
    fn: Callable[[], T],
    max_retries: int = 3,
    sleep_fn: Callable[[float], None] | None = None,
    base_delay: float = 0.5,
) -> T:
    """最多尝试 ``max_retries`` 次（``max_retries=0`` 视为 1 次，不退避）。"""
    if sleep_fn is None:
        sleep_fn = time.sleep
    attempts = max(max_retries, 1)
    last: Exception | None = None
    for index in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if not is_retryable(exc) or index == attempts - 1:
                raise
            sleep_fn(base_delay * (2**index))
    assert last is not None
    raise last
