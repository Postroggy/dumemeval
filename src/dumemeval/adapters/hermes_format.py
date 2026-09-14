"""Hermes 官方 memory 文件格式（纯函数，与 memory_tool.py 对齐）。

从 hermes_builtin adapter 拆出：条目分隔/解析/快照块渲染，无 adapter 状态。
"""

from __future__ import annotations

# 条目分隔符（与 hermes memory_tool.py ENTRY_DELIMITER 一致）
ENTRY_DELIMITER = "\n§\n"

# 文件默认字符上限（与 hermes MemoryStore 默认一致）
DEFAULT_MEMORY_LIMIT = 2200
DEFAULT_USER_LIMIT = 1375

# system prompt 块的标题（与 hermes MEMORY_BLOCK_HEADERS 一致）
MEMORY_BLOCK_HEADERS = {
    "memory": "MEMORY (your personal notes)",
    "user": "USER PROFILE (who the user is)",
}


def parse_entries(raw: str) -> list[str]:
    """按 § 分隔符解析 memory 文件为条目列表（strip + 去空 + 去重保序）。"""
    if not raw.strip():
        return []
    entries = [e.strip() for e in raw.split(ENTRY_DELIMITER)]
    seen: list[str] = []
    for e in entries:
        if e and e not in seen:
            seen.append(e)
    return seen


def render_block(target: str, entries: list[str], char_limit: int) -> str:
    """渲染 system prompt 块（═ 分隔线 + 标题[百分比 — chars] + 内容）。"""
    if not entries:
        return ""
    content = ENTRY_DELIMITER.join(entries)
    current = len(content)
    pct = min(100, int((current / char_limit) * 100)) if char_limit > 0 else 0
    header = f"{MEMORY_BLOCK_HEADERS[target]} [{pct}% — {current:,}/{char_limit:,} chars]"
    separator = "═" * 46
    return f"{separator}\n{header}\n{separator}\n{content}"
