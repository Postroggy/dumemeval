"""生命周期事件钩子。

设计要点：
- 评测方可以订阅生命周期事件（session_start/session_end/memory_collected）
- 事件是异步回调（awaitable），支持评测方在关键节点插入逻辑
- 单向依赖：只依赖 models
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from ..models import SessionSpec

# 事件回调类型：接收 (event, session, context)
LifecycleCallback = Callable[[str, SessionSpec, dict[str, Any]], Awaitable[None]]


class LifecycleEvent(StrEnum):
    """生命周期事件。"""

    EVAL_START = "eval_start"  # 整个评测开始
    EVAL_END = "eval_end"  # 整个评测结束
    SESSION_START = "session_start"  # 单个 session 开始
    SESSION_END = "session_end"  # 单个 session 结束
    MEMORY_COLLECTED = "memory_collected"  # 跨 session memory 收集完成
    MEMORY_INJECTED = "memory_injected"  # 跨 session memory 注入完成
    ERROR = "error"  # 出错


class LifecycleHooks:
    """生命周期事件订阅器。

    用法：
        hooks = LifecycleHooks()
        hooks.on(LifecycleEvent.SESSION_END, my_async_handler)
        await hooks.emit(LifecycleEvent.SESSION_END, session, ctx)
    """

    def __init__(self) -> None:
        self._handlers: dict[LifecycleEvent, list[LifecycleCallback]] = {}

    def on(self, event: LifecycleEvent, handler: LifecycleCallback) -> None:
        """订阅事件。"""
        self._handlers.setdefault(event, []).append(handler)

    def off(self, event: LifecycleEvent, handler: LifecycleCallback) -> None:
        """取消订阅。"""
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    async def emit(self, event: LifecycleEvent, session: SessionSpec, ctx: dict[str, Any]) -> None:
        """触发事件（顺序执行所有订阅者）。"""
        for handler in self._handlers.get(event, []):
            await handler(event, session, ctx)

    def has_handlers(self, event: LifecycleEvent) -> bool:
        return bool(self._handlers.get(event))
