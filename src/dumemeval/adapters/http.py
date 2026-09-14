"""HTTP 型 Memory 适配器：外部 HTTP memory 服务（Mem0/Letta/自建 server）。

协议（wrap/add，与 MemoryArena memory server 兼容）：
- POST /memory/initialize  {user_id, memory_system_name}
- POST /memory/add         {user_id, memory_system_name, chunk}
- POST /memory/wrap_user_prompt {user_id, memory_system_name, question}
  → 返回包装了 memory 上下文的 prompt

Quality 观测 = 在 adapter 层记录每次 add/search 调用（不侵入 memory 服务本身）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from ..core.retry import call_with_retries
from ..models import EvalTask, MemoryOp, SessionSpec
from .base import BaseMemoryAdapter
from .registry import register_adapter


@register_adapter
class HttpMemoryAdapter(BaseMemoryAdapter):
    """HTTP memory 后端。"""

    type_name = "http"

    def setup(self, task: EvalTask) -> None:
        if not self.spec.base_url:
            raise ValueError(f"HTTP adapter {self.name!r} requires base_url")
        self.base_url = self.spec.base_url.rstrip("/")
        self.user_id = self.spec.user_id or f"dumemeval_{self.name}"
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._post(
            "/memory/initialize",
            {
                "user_id": self.user_id,
                "memory_system_name": self.name,
            },
        )
        self._ops.clear()
        self._record("setup", 0)

    def inject(self, session: SessionSpec, session_ctx: dict[str, Any]) -> None:
        """HTTP 型：把连接信息注入 agent 环境（env 变量）。

        agent 通过 env 拿到 memory 服务地址与 user_id。
        """
        env = session_ctx.setdefault("agent_env", {})
        env["MEMORY_SERVER_URL"] = self.base_url
        env["MEMORY_USER_ID"] = self.user_id
        env["MEMORY_SYSTEM_NAME"] = self.name
        self._record("inject", session.id, content=f"env: MEMORY_SERVER_URL={self.base_url}")

    def memory_usage_hint(self) -> str | None:
        return (
            f"持久记忆服务：{self.base_url}（env MEMORY_SERVER_URL，user_id={self.user_id}）。"
            "服务端点：/memory/add 写入、/memory/wrap_user_prompt 检索"
        )

    def snapshot(self, session: SessionSpec, snapshot_dir: Path) -> Path:
        """HTTP 型：快照 = 导出当前 memory 内容（依赖服务提供导出接口）。"""

        snap = snapshot_dir / f"session_{session.id}"
        snap.mkdir(parents=True, exist_ok=True)
        # 尝试从服务导出 memory（若服务不支持，跳过，仅记录）
        try:
            resp = self.session.get(
                f"{self.base_url}/memory/export",
                params={"user_id": self.user_id},
                timeout=30,
            )
            if resp.status_code == 200:
                (snap / "memory_export.json").write_text(resp.text)
        except requests.RequestException as e:
            # 服务不支持导出接口时优雅降级（只记录，不影响快照目录）
            import logging

            logging.getLogger(__name__).debug("memory export 不可用: %s", e)
        self._record("snapshot", session.id, content=str(snap))
        return snap

    def observe(self, session: SessionSpec) -> list[MemoryOp]:
        return [op for op in self._ops if op.session_id == session.id]

    def add(self, chunk: str, session_id: int) -> None:
        self._post(
            "/memory/add",
            {
                "user_id": self.user_id,
                "memory_system_name": self.name,
                "chunk": chunk,
            },
        )
        self._record("add", session_id, content=chunk)

    def wrap_user_prompt(self, question: str, session_id: int) -> str:
        resp = self._post(
            "/memory/wrap_user_prompt",
            {
                "user_id": self.user_id,
                "memory_system_name": self.name,
                "question": question,
            },
        )
        prompt = resp.get("prompt", "")
        self._record("search", session_id, query=question, content=prompt[:500])
        return str(prompt)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        def _once() -> dict[str, Any]:
            resp = self.session.post(f"{self.base_url}{path}", json=payload, timeout=300)
            resp.raise_for_status()
            body = resp.json()
            return body if isinstance(body, dict) else {}

        return call_with_retries(_once)
