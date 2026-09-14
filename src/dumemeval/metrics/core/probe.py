"""内置 memory 探测：从 session jsonl 提取 memory 读写事件。

不是指标计算器（不实现 MetricCalculator）——它是 Quality 的数据源之一：
对 Claude Code / Hermes 这类内置 memory，无法直接看内部写入，
只能从 agent 的 session 记录里还原「它有没有读写过 memory」。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["QualityProbe"]


class QualityProbe:
    """内置 memory 探测。

    对 Claude Code / Hermes 这类内置 memory，无法直接看内部写入，
    通过分析 session jsonl 提取 memory 相关事件（memory 写入/读取）。

    用法：
        probe = QualityProbe()
        events = probe.extract_from_session("path/to/session.jsonl")
        probe.scan_dir("path/to/sessions")  # 扫整个目录
    """

    _MEMORY_KEYWORDS = ("memory", "记住", "记忆", "偏好", "记得", "remember")

    def __init__(self, session_dir: str | None = None):
        self.session_dir = session_dir

    def extract_from_session(self, session_jsonl: str) -> list[dict[str, Any]]:
        """从 session jsonl 提取 memory 相关事件。"""
        events: list[dict[str, Any]] = []
        path = Path(session_jsonl)
        if not path.exists():
            return events

        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = self._extract_from_record(record)
            if event is not None:
                events.append(event)
        return events

    def _extract_from_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        message = record.get("message") or {}
        content = self._content_text(message.get("content"))

        tool_use = message.get("tool_use") or {}
        tool_name = tool_use.get("name", "")
        if tool_name in ("Write", "Edit", "NotebookEdit") and self._is_memory_path(
            tool_use.get("input", {}).get("file_path", "")
        ):
            return {
                "type": "memory_write",
                "session_id": record.get("sessionId", ""),
                "content": content[:500],
                "timestamp": record.get("timestamp", 0.0),
            }
        if tool_name == "Read" and self._is_memory_path(tool_use.get("input", {}).get("file_path", "")):
            return {
                "type": "memory_read",
                "session_id": record.get("sessionId", ""),
                "content": content[:500],
                "timestamp": record.get("timestamp", 0.0),
            }

        if content and any(kw in content.lower() for kw in self._MEMORY_KEYWORDS):
            return {
                "type": "memory_mention",
                "session_id": record.get("sessionId", ""),
                "content": content[:500],
                "timestamp": record.get("timestamp", 0.0),
            }
        return None

    @staticmethod
    def _content_text(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(str(part.get("text", "")))
                    elif part.get("type") == "tool_result":
                        inner = part.get("content")
                        if isinstance(inner, str):
                            parts.append(inner)
                elif isinstance(part, str):
                    parts.append(part)
            return "\n".join(parts)
        return str(content)

    @staticmethod
    def _is_memory_path(path: str) -> bool:
        lower = path.lower()
        return "/memory/" in lower or lower.endswith("/memory") or "memory" in lower

    def scan_dir(self, session_dir: str | None = None) -> list[dict[str, Any]]:
        """扫描目录下所有 session jsonl，聚合 memory 事件。"""
        scan_root = Path(session_dir or self.session_dir or "")
        if not scan_root.exists():
            return []
        events: list[dict[str, Any]] = []
        for p in sorted(scan_root.rglob("*.jsonl")):
            events.extend(self.extract_from_session(str(p)))
        return events
