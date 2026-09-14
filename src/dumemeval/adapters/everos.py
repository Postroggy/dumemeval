"""EverOS 官方 memory runtime 适配器（被测后端，非 benchmark）。

EverOS（EverMind）是 HTTP memory 服务：Markdown 为真源 + SQLite/LanceDB 索引。
其官方评测（benchmarks/run.py）即 LoCoMo——四阶段管线：
ADD → wait_ready → SEARCH → ANSWER → JUDGE（judge_runs 次多数投票）。
在 dumemeval 中：memory.type=everos 接入服务本体，评测数据走已支持的 locomo。

官方 API（benchmarks/run.py L648-780，默认 base_url=http://localhost:8000）：
- POST /api/v1/memory/add    {session_id, app_id, project_id, messages}
    message: {sender_id, sender_name, role: "user", timestamp(ms),
              content: [{type: "text", text}]}
- POST /api/v1/memory/flush  {session_id, app_id, project_id}
- POST /api/v1/memory/search {query, method, top_k, user_id, app_id, project_id}
    → {data: {episodes: [], profiles: []}}

官方默认（benchmarks/config.toml）：method="agentic"、top_k=10、batch_size=25、
app_id="locomo_benchmark"、eval_owner="speaker_a"（按 owner 分区检索）。

语义映射：
- setup：命名空间隔离（project_id 每次评测唯一，避免 EverOS 无清空 API 时
  交叉污染；官方 runner 用固定命名空间，可比性场景可显式传 project_id）
- seed_history：conversation_sessions 逐 session ADD+FLUSH（官方 ADD 阶段；
  本地数据无 timestamp 时按 session 序递增合成）
- inject：对问题逐个 SEARCH（官方 SEARCH 阶段）→ episodes 注入
  agent_env["EVEROS_CONTEXT"]（官方 ANSWER 阶段的 context），同时注入
  base_url/命名空间 env（agent 可继续主动检索）
- 官方 wait_ready（cascade/OME 索引轮询，SQLite 直查）属 runner 部署细节，
  不在此实现——评测需确保 server 完成索引（或经 spec.config["ready_wait_sec"]
  简单轮询首个 search 成功）
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from ..core.retry import call_with_retries
from ..models import EvalTask, MemoryOp, SessionSpec
from .base import BaseMemoryAdapter
from .registry import register_adapter

# 官方 benchmarks/config.toml 默认值
DEFAULT_METHOD = "agentic"
DEFAULT_TOP_K = 10
DEFAULT_BATCH_SIZE = 25
DEFAULT_APP_ID = "locomo_benchmark"
DEFAULT_OWNER = "speaker_a"


@register_adapter
class EverosMemoryAdapter(BaseMemoryAdapter):
    """EverOS HTTP memory 后端（官方 /api/v1/memory/* 协议）。

    spec 约定：
        base_url : EverOS server（默认 http://localhost:8000）
        user_id  : 检索的 owner 分区（官方 eval_owner，默认 speaker_a）
        config["app_id"]      : 默认 "locomo_benchmark"（官方值）
        config["project_id"]  : 不传则每次评测生成唯一值（隔离）
        config["method"]      : 检索方法（agentic/hybrid/vector/keyword）
        config["top_k"]       : 每题检索 episodes 数
        config["batch_size"]  : /add 每批消息数（官方 25）
        config["ready_wait_sec"] : inject 前轮询 search 就绪的秒数（0 不等待）
    """

    type_name = "everos"

    def setup(self, task: EvalTask) -> None:
        self.base_url = (self.spec.base_url or "http://localhost:8000").rstrip("/")
        cfg = self.spec.config
        self.app_id = str(cfg.get("app_id", DEFAULT_APP_ID))
        # 隔离：未显式指定 project_id 时每次评测唯一（EverOS 无清空 API）
        self.project_id = str(cfg.get("project_id") or f"dumemeval_{uuid.uuid4().hex[:8]}")
        self.owner_id = self.spec.user_id or DEFAULT_OWNER
        self.method = str(cfg.get("method", DEFAULT_METHOD))
        self.top_k = int(cfg.get("top_k", DEFAULT_TOP_K))
        self.batch_size = int(cfg.get("batch_size", DEFAULT_BATCH_SIZE))
        self.ready_wait_sec = float(cfg.get("ready_wait_sec", 0))
        self._task = task
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._ops.clear()
        self._record("setup", 0, content=f"project_id={self.project_id}")

    # ── 官方 ADD 阶段 ─────────────────────────────────────────────────────

    def seed_history(self, task: EvalTask) -> None:
        """conversation_sessions 逐 session ADD+FLUSH（官方 run_add_phase）。"""
        sessions = self._extract_sessions(task)
        for sess_idx, sess in enumerate(sessions):
            session_id = f"{self.name}_conv0_s{sess_idx}"
            valid = [m for m in sess if isinstance(m, dict) and str(m.get("text", "")).strip()]
            messages = [
                {
                    "sender_id": f"{str(m.get('speaker', 'user')).lower()}_conv0",
                    "sender_name": str(m.get("speaker", "user")),
                    "role": "user",
                    # 本地数据无 timestamp：session 基准 + 消息内递增合成（官方从数据解析 ms）
                    "timestamp": (sess_idx + 1) * 60_000 + msg_idx * 1000,
                    "content": [{"type": "text", "text": str(m.get("text", ""))}],
                }
                for msg_idx, m in enumerate(valid)
            ]
            if not messages:
                continue
            batches = [messages[i : i + self.batch_size] for i in range(0, len(messages), self.batch_size)]
            for batch in batches:
                self._post(
                    "/api/v1/memory/add",
                    {
                        "session_id": session_id,
                        "app_id": self.app_id,
                        "project_id": self.project_id,
                        "messages": batch,
                    },
                )
            self._post(
                "/api/v1/memory/flush",
                {"session_id": session_id, "app_id": self.app_id, "project_id": self.project_id},
            )
            self._record("add", 0, content=f"{session_id}: {len(messages)} msgs flushed")

    @staticmethod
    def _extract_sessions(task: EvalTask) -> list[list[dict[str, Any]]]:
        if not isinstance(task.data, dict):
            return []
        sessions = task.data.get("conversation_sessions") or []
        return [s for s in sessions if isinstance(s, list)]

    # ── 官方 SEARCH 阶段 + agent 注入 ─────────────────────────────────────

    def search(self, question: str) -> dict[str, Any]:
        """官方 _search_one：/search（500 退避重试 3 次，官方 _SEARCH_RETRIES）。"""
        payload = {
            "query": question,
            "method": self.method,
            "top_k": self.top_k,
            "user_id": self.owner_id,
            "app_id": self.app_id,
            "project_id": self.project_id,
        }
        resp = self._post_with_retry("/api/v1/memory/search", payload)
        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        return {"episodes": data.get("episodes", []), "profiles": data.get("profiles", [])}

    def inject(self, session: SessionSpec, session_ctx: dict[str, Any]) -> None:
        """注入检索上下文（官方 SEARCH→ANSWER）+ 服务连接信息（agent 可主动检索）。"""
        if self.ready_wait_sec > 0:
            self._wait_ready()
        env = session_ctx.setdefault("agent_env", {})
        env["EVEROS_BASE_URL"] = self.base_url
        env["EVEROS_APP_ID"] = self.app_id
        env["EVEROS_PROJECT_ID"] = self.project_id
        env["EVEROS_OWNER_ID"] = self.owner_id

        results: dict[str, Any] = {}
        for question in self._questions_for(session):
            hit = self.search(question)
            results[question] = hit
            self._record("search", session.id, query=question, content=f"{len(hit['episodes'])} episodes")
        if results:
            env["EVEROS_CONTEXT"] = self._render_context(results)
        self._record("inject", session.id, content=f"{len(results)} queries")

    def memory_usage_hint(self) -> str | None:
        return (
            f"持久记忆服务（EverOS）：{self.base_url}（env EVEROS_BASE_URL，"
            f"project={self.project_id}），端点 /api/v1/memory/search 可主动检索"
        )

    def _questions_for(self, session: SessionSpec) -> list[str]:
        """本 session 要检索的问题：session.query 优先，QA session 逐题。"""
        if session.query:
            return [session.query]
        if self._task is not None and isinstance(self._task.data, dict):
            return [
                str(q.get("question", ""))
                for q in self._task.data.get("qa", [])
                if isinstance(q, dict) and str(q.get("question", "")).strip()
            ]
        return []

    @staticmethod
    def _render_context(results: dict[str, Any]) -> str:
        """检索结果 → ANSWER 阶段的 context 文本（官方 answer 用的 episodes 上下文）。"""
        parts: list[str] = []
        for question, hit in results.items():
            lines = [f"Q: {question}"]
            for ep in hit.get("episodes", []):
                text = ep.get("text") or ep.get("content") or json.dumps(ep, ensure_ascii=False)
                lines.append(f"- {text}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    def _wait_ready(self) -> None:
        """轮询首个 search 成功即视为就绪（官方 cascade/OME SQLite 轮询的轻量版）。"""
        deadline = time.monotonic() + self.ready_wait_sec
        probe = self._questions_for(SessionSpec(id=0, instruction=""))
        question = probe[0] if probe else "ping"
        while time.monotonic() < deadline:
            try:
                self.search(question)
                return
            except requests.RequestException:
                time.sleep(2.0)
        raise TimeoutError(f"EverOS search 未在 {self.ready_wait_sec}s 内就绪")

    # ── 生命周期其余部分 ─────────────────────────────────────────────────

    def snapshot(self, session: SessionSpec, snapshot_dir: Path) -> Path:
        """快照 = 本 session 的 ops 摘要（HTTP 型无文件可导出；详细 episodes
        已在 inject 时注入 agent_env 并记入 ops）。"""
        snap = snapshot_dir / f"session_{session.id}"
        snap.mkdir(parents=True, exist_ok=True)
        summary = {
            "project_id": self.project_id,
            "ops": [op.model_dump() for op in self.observe(session)],
        }
        (snap / "everos_ops.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._record("snapshot", session.id, content=str(snap))
        return snap

    def observe(self, session: SessionSpec) -> list[MemoryOp]:
        return [op for op in self._ops if op.session_id == session.id]

    # ── HTTP 工具 ────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self._session.post(f"{self.base_url}{path}", json=payload, timeout=300)
        resp.raise_for_status()
        body = resp.json()
        return body if isinstance(body, dict) else {}

    def _post_with_retry(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """官方 search 重试：仅瞬时 5xx / 网络错误退避，最多 3 次。"""
        return call_with_retries(lambda: self._post(path, payload), max_retries=3, base_delay=2.0)
