"""Hermes 官方内置 memory（builtin provider）适配器。

对齐 hermes-agent `tools/memory_tool.py`（MemoryStore）语义：
MEMORY.md（agent 笔记，2200 chars）+ USER.md（用户画像，1375 chars），
条目 `\n§\n` 分隔、原子写盘；session 启动时冻结快照注入 system prompt。
文件格式与快照渲染见 hermes_format.py；写操作对齐官方 memory 工具
add/replace/remove（唯一子串匹配，重复/超限/多匹配拒绝）。

BYOK：inject 时生成 hermes config.yaml（provider: custom + base_url），
挂载覆盖 Harbor 默认 config（官方支持的任意 OpenAI 兼容端点）。

Quality 观测 = 记录 add/replace/remove/snapshot 操作；read_memory_files
导出 MEMORY.md/USER.md 内容供 Quality 评测。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..models import EvalTask, MemoryOp, MemorySpec, SessionSpec
from .base import BaseMemoryAdapter, declare_mount

# 格式层再导出（parse_entries/render_block 等公开符号，测试/外部可直接从本模块引用）
from .hermes_format import (  # noqa: F401
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_USER_LIMIT,
    ENTRY_DELIMITER,
    MEMORY_BLOCK_HEADERS,
    parse_entries,
    render_block,
)
from .registry import register_adapter

# 容器内 Hermes 路径（$HERMES_HOME 下）
CONTAINER_MEMORIES_DIR = "/tmp/hermes/memories"
CONTAINER_CONFIG_PATH = "/tmp/hermes/config.yaml"


@register_adapter
class HermesBuiltinMemoryAdapter(BaseMemoryAdapter):
    """Hermes 官方内置 memory（MEMORY.md / USER.md 双文件）适配器。

    spec 约定：
        path          : host 侧 memories 目录（默认 <results>/memory/<name>）
        user_id       : 无（内置 memory 按 profile 隔离，由 HERMES_HOME 决定）
        config["targets"] : 启用哪些文件（"memory" / "user"，默认都启用）
        config["memory_limit"] / config["user_limit"] : 字符上限
    """

    type_name = "hermes_builtin"

    def __init__(self, spec: MemorySpec) -> None:
        super().__init__(spec)
        self.memory_dir = Path(spec.path) if spec.path else Path("results") / "memory" / spec.name
        self.enabled_targets: set[str] = {"memory", "user"}
        self.memory_limit = DEFAULT_MEMORY_LIMIT
        self.user_limit = DEFAULT_USER_LIMIT

    def setup(self, task: EvalTask) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        # 清空重建（保证干净起点，上一次 run 的残留会污染 Quality）
        for item in self.memory_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        targets = self.spec.config.get("targets") or ["memory", "user"]
        self.enabled_targets = set(targets)
        self.memory_limit = int(self.spec.config.get("memory_limit", DEFAULT_MEMORY_LIMIT))
        self.user_limit = int(self.spec.config.get("user_limit", DEFAULT_USER_LIMIT))

        self._entries: dict[str, list[str]] = {"memory": [], "user": []}
        self._ops.clear()
        self._record("setup", 0)

    # ── 路径与条目工具（对齐 memory_tool.py）──────────────────────────────

    def _path_for(self, target: str) -> Path:
        return self.memory_dir / ("USER.md" if target == "user" else "MEMORY.md")

    def _char_limit(self, target: str) -> int:
        return self.user_limit if target == "user" else self.memory_limit

    def _load_entries(self, target: str) -> list[str]:
        """从磁盘读条目（文件不存在视为空）。"""
        path = self._path_for(target)
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return []
        return parse_entries(raw)

    def _save_entries(self, target: str, entries: list[str]) -> None:
        """原子写盘（temp + rename，对齐 atomic_write_text）。"""
        path = self._path_for(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = ENTRY_DELIMITER.join(entries) if entries else ""
        tmp = path.with_name(f".mem_{path.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)

    # ── 生命周期（BaseMemoryAdapter）──────────────────────────────────────

    def inject(self, session: SessionSpec, session_ctx: dict[str, Any]) -> None:
        """把 memory 快照注入 agent 环境。

        - agent_env["HERMES_MEMORY_DIR"]: memories 目录
        - agent_env["HERMES_MEMORY_SNAPSHOT"]: 冻结快照（═ 分隔线格式，对齐
          MemoryStore.format_for_system_prompt——session 期间不变）
        - 挂载（走统一 memory_mounts 契约，执行器不认识 hermes 专有键）：
          memories 目录 → $HERMES_HOME/memories；BYOK config.yaml → 覆盖默认 config
        """
        env = session_ctx.setdefault("agent_env", {})
        env["HERMES_MEMORY_DIR"] = str(self.memory_dir)
        snapshot = self._build_snapshot()
        if snapshot:
            env["HERMES_MEMORY_SNAPSHOT"] = snapshot

        declare_mount(session_ctx, self.memory_dir, CONTAINER_MEMORIES_DIR)
        # BYOK：生成 hermes config.yaml（model.base_url/api_key），挂载覆盖
        # Harbor 生成的默认 config（官方支持 provider: custom 任意 OpenAI 兼容端点）
        config_path = self._write_config_yaml()
        if config_path:
            declare_mount(session_ctx, config_path, CONTAINER_CONFIG_PATH)
        self._record("inject", session.id, content=f"snapshot {len(snapshot)} chars")

    def memory_usage_hint(self) -> str | None:
        return (
            f"持久记忆由 Hermes memory 工具管理：目录 {CONTAINER_MEMORIES_DIR}，"
            "session 启动时已把快照注入你的系统提示；新信息用工具写入（add/replace/remove）"
        )

    def _write_config_yaml(self) -> Path | None:
        """生成 BYOK hermes config.yaml（model.base_url + api_key + provider: custom）。

        spec.config:
            base_url: OpenAI 兼容端点（必填，如 https://.../v1）
            api_key : API key（必填）
            model   : 模型名（默认 HermesBuiltinMemoryAdapter 无；用 spec.config["model"]）
        """
        import os

        base_url = self.spec.config.get("base_url") or os.environ.get("MODEL_BASE_URL")
        api_key = self.spec.config.get("api_key") or os.environ.get("MODEL_API_KEY")
        model = self.spec.config.get("model") or os.environ.get("MODEL_NAME")
        if not model:
            raise ValueError(
                "hermes_builtin 需要 model：在 memory.config.model 或环境变量 MODEL_NAME 设置"
                "（框架不预设厂商模型）"
            )
        if not base_url:
            return None
        config = {
            "model": {
                "default": model,
                "provider": "custom",
                "base_url": base_url,
                "api_key": api_key or "",
            },
            "agent": {"max_turns": 90},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "toolsets": ["hermes-cli"],
        }
        # 落 memory_dir 内（per-task 隔离；跨 task 并行时不共享写同一文件）
        path = self.memory_dir / "hermes-config.yaml"
        import yaml

        path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return path

    def _build_snapshot(self) -> str:
        """构建冻结快照（memory + user 两块，对齐 load_from_disk 的 snapshot）。"""
        parts = []
        for target in ("memory", "user"):
            if target not in self.enabled_targets:
                continue
            entries = self._load_entries(target)
            block = render_block(target, entries, self._char_limit(target))
            if block:
                parts.append(block)
        return "\n\n".join(parts)

    def seed_history(self, task: EvalTask) -> None:
        """评测前把历史对话/事实灌入 MEMORY.md（对齐 add 语义：追加条目）。

        task.data 支持：
        - data["history_messages"]: [{role, content}] → 每条的 content 作一条记忆
        - data["conversation_sessions"]: [[{speaker, text}]] → 每条 text 作一条记忆
        """
        messages = self._extract_history_messages(task)
        if not messages:
            return
        for m in messages:
            content = str(m.get("content") or m.get("text") or "").strip()
            if content:
                self.add(content, target="memory", session_id=0)

    @staticmethod
    def _extract_history_messages(task: EvalTask) -> list[dict[str, Any]]:
        if not isinstance(task.data, dict):
            return []
        if task.data.get("history_messages"):
            return [dict(m) for m in task.data["history_messages"]]
        sessions = task.data.get("conversation_sessions") or []
        messages: list[dict[str, Any]] = []
        for sess in sessions:
            if not isinstance(sess, list):
                continue
            for msg in sess:
                if isinstance(msg, dict):
                    messages.append(dict(msg))
        return messages

    def snapshot(self, session: SessionSpec, snapshot_dir: Path) -> Path:
        """快照当前 memory 文件到 snapshot_dir/session_{id}/。"""
        snap = snapshot_dir / f"session_{session.id}"
        snap.mkdir(parents=True, exist_ok=True)
        for target in ("memory", "user"):
            src = self._path_for(target)
            if src.exists():
                shutil.copy2(src, snap / src.name)
        self._record("snapshot", session.id, content=str(snap))
        return snap

    def observe(self, session: SessionSpec) -> list[MemoryOp]:
        return [op for op in self._ops if op.session_id == session.id]

    def read_memory_files(self) -> dict[str, str]:
        """读取 MEMORY.md / USER.md 内容（Quality 评测用）。"""
        result: dict[str, str] = {}
        for target in ("memory", "user"):
            path = self._path_for(target)
            if path.exists():
                try:
                    result[path.name] = path.read_text(encoding="utf-8")
                except OSError:
                    continue
        return result

    # ── 写操作（对齐 memory 工具 add/replace/remove）──────────────────────

    def add(self, content: str, target: str = "memory", session_id: int = 0) -> dict[str, Any]:
        """追加一条条目（拒绝空/重复/超限）。"""
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content cannot be empty."}
        if target not in self.enabled_targets:
            return {"success": False, "error": f"Target {target!r} disabled."}

        entries = self._load_entries(target)
        if content in entries:
            return {"success": False, "error": "Entry already exists (no duplicate added)."}

        new_entries = [*entries, content]
        new_total = len(ENTRY_DELIMITER.join(new_entries))
        if new_total > self._char_limit(target):
            current = len(ENTRY_DELIMITER.join(entries))
            return {
                "success": False,
                "error": (
                    f"Memory at {current:,}/{self._char_limit(target):,} chars. "
                    "Adding this entry would exceed the limit. Consolidate first."
                ),
            }

        self._save_entries(target, new_entries)
        self._record("add", session_id, content=content)
        return {"success": True, "target": target, "entry_count": len(new_entries)}

    def replace(
        self, old_text: str, new_content: str, target: str = "memory", session_id: int = 0
    ) -> dict[str, Any]:
        """找到含 old_text 子串的条目并替换（唯一匹配）。"""
        old_text = old_text.strip()
        new_content = new_content.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}
        if not new_content:
            return {"success": False, "error": "new_content cannot be empty. Use 'remove' to delete entries."}
        if target not in self.enabled_targets:
            return {"success": False, "error": f"Target {target!r} disabled."}

        entries = self._load_entries(target)
        matches = [e for e in entries if old_text in e]
        if not matches:
            return {"success": False, "error": f"No entry matched '{old_text}'."}
        if len(matches) > 1:
            return {"success": False, "error": f"Multiple entries matched '{old_text}'. Be more specific."}

        new_entries = [new_content if e == matches[0] else e for e in entries]
        self._save_entries(target, new_entries)
        self._record("replace", session_id, content=f"{old_text} -> {new_content}")
        return {"success": True, "target": target, "entry_count": len(new_entries)}

    def remove(self, old_text: str, target: str = "memory", session_id: int = 0) -> dict[str, Any]:
        """找到含 old_text 子串的条目并删除（唯一匹配）。"""
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}
        if target not in self.enabled_targets:
            return {"success": False, "error": f"Target {target!r} disabled."}

        entries = self._load_entries(target)
        matches = [e for e in entries if old_text in e]
        if not matches:
            return {"success": False, "error": f"No entry matched '{old_text}'."}
        if len(matches) > 1:
            return {"success": False, "error": f"Multiple entries matched '{old_text}'. Be more specific."}

        new_entries = [e for e in entries if e != matches[0]]
        self._save_entries(target, new_entries)
        self._record("remove", session_id, content=old_text)
        return {"success": True, "target": target, "entry_count": len(new_entries)}
