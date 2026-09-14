"""测试：EverOS memory adapter（官方 /api/v1/memory/* 协议对齐）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.adapters.everos import EverosMemoryAdapter
from dumemeval.adapters.registry import create_adapter
from dumemeval.models import EvalTask, MemorySpec, SessionSpec


def _task() -> EvalTask:
    return EvalTask(
        name="locomo_0",
        sessions=[SessionSpec(id=1, instruction="read", memory_inject=True)],
        data={
            "conversation_sessions": [
                [
                    {"speaker": "Alice", "text": "I bought a car."},
                    {"speaker": "Bob", "text": "Nice!"},
                ],
                [{"speaker": "Alice", "text": "It is red."}],
            ],
            "qa": [
                {"question": "What color is the car?", "answer": "red", "category": 4},
                {"question": "What did Alice buy?", "answer": "a car", "category": 4},
            ],
        },
        benchmark="locomo",
    )


def _resp(body: dict[str, Any] | None = None, status: int = 200) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body or {}
    if status >= 400:
        m.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}", response=m)
    return m


class _Recorder:
    """捕获 Session.post 调用并按路由返回官方响应。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, json: dict[str, Any] | None = None, **kw: Any) -> MagicMock:
        path = url.split("/api/v1")[-1]
        self.calls.append((path, json or {}))
        if path == "/memory/search":
            return _resp({"data": {"episodes": [{"text": "Alice's car is red"}], "profiles": []}})
        return _resp({"ok": True})


def _make() -> EverosMemoryAdapter:
    return EverosMemoryAdapter(MemorySpec(name="everos", type="everos", base_url="http://localhost:8000"))


class TestRegistryAndSpec:
    def test_registry_creates_everos(self) -> None:
        adapter = create_adapter(MemorySpec(name="everos", type="everos"))
        assert isinstance(adapter, EverosMemoryAdapter)

    def test_setup_defaults(self) -> None:
        a = _make()
        a.setup(_task())
        assert a.base_url == "http://localhost:8000"
        assert a.app_id == "locomo_benchmark"  # 官方 config.toml 默认
        assert a.project_id.startswith("dumemeval_")  # 未显式指定 → 唯一隔离
        assert a.owner_id == "speaker_a"  # 官方 eval_owner
        assert a.method == "agentic" and a.top_k == 10  # 官方搜索默认

    def test_project_id_isolated_between_runs(self) -> None:
        a1, a2 = _make(), _make()
        a1.setup(_task())
        a2.setup(_task())
        assert a1.project_id != a2.project_id  # EverOS 无清空 API → 靠命名空间隔离


class TestAddPhase:
    def test_seed_history_official_payload(self) -> None:
        """ADD+FLUSH 官方 payload：session_id 命名 / sender_id / content 结构。"""
        a = _make()
        a.setup(_task())
        rec = _Recorder()
        with patch.object(type(a._session), "post", rec):
            a.seed_history(_task())

        adds = [p for path, p in rec.calls if path == "/memory/add"]
        flushes = [p for path, p in rec.calls if path == "/memory/flush"]
        assert len(adds) == 2 and len(flushes) == 2  # 每 session 一次 flush
        first = adds[0]
        assert first["app_id"] == "locomo_benchmark" and first["project_id"] == a.project_id
        msg = first["messages"][0]
        assert msg["sender_id"] == "alice_conv0"  # 官方 sender 格式
        assert msg["role"] == "user"
        assert msg["content"] == [{"type": "text", "text": "I bought a car."}]
        assert first["session_id"] == "everos_conv0_s0"
        assert flushes[0]["session_id"] == first["session_id"]

    def test_batching(self) -> None:
        """超过 batch_size（官方 25）的消息分批 add。"""
        a = _make()
        task = _task()
        task.data["conversation_sessions"] = [[{"speaker": "A", "text": f"m{i}"} for i in range(60)]]
        a.setup(task)
        rec = _Recorder()
        with patch.object(type(a._session), "post", rec):
            a.seed_history(task)
        adds = [p for path, p in rec.calls if path == "/memory/add"]
        assert [len(p["messages"]) for p in adds] == [25, 25, 10]


class TestSearchAndInject:
    def test_inject_searches_each_qa_and_injects_context(self) -> None:
        a = _make()
        a.setup(_task())
        rec = _Recorder()
        ctx: dict[str, Any] = {}
        with patch.object(type(a._session), "post", rec):
            a.inject(SessionSpec(id=2, instruction="answer questions", memory_inject=True), ctx)

        searches = [p for path, p in rec.calls if path == "/memory/search"]
        assert len(searches) == 2  # QA session：逐题检索（官方 SEARCH 阶段）
        assert searches[0]["method"] == "agentic" and searches[0]["top_k"] == 10
        assert searches[0]["user_id"] == "speaker_a"
        assert searches[0]["project_id"] == a.project_id
        # ANSWER 阶段的 context 注入（episodes 文本）+ 主动检索连接信息
        env = ctx["agent_env"]
        assert "Alice's car is red" in env["EVEROS_CONTEXT"]
        assert env["EVEROS_BASE_URL"] == "http://localhost:8000"
        assert env["EVEROS_PROJECT_ID"] == a.project_id
        assert "Alice's car is red" in env["EVEROS_CONTEXT"]

    def test_session_query_single_search(self) -> None:
        a = _make()
        a.setup(_task())
        rec = _Recorder()
        ctx: dict[str, Any] = {}
        with patch.object(type(a._session), "post", rec):
            a.inject(SessionSpec(id=1, instruction="q", query="What color?", memory_inject=True), ctx)
        searches = [p for path, p in rec.calls if path == "/memory/search"]
        assert len(searches) == 1 and searches[0]["query"] == "What color?"

    def test_search_retries_on_5xx(self) -> None:
        """官方 _SEARCH_RETRIES：5xx 退避重试，4xx 直接抛。"""
        a = _make()
        a.setup(_task())

        responses = [_resp({"err": "x"}, 500), _resp({"err": "x"}, 500), _resp({"data": {"episodes": []}})]
        with (
            patch.object(type(a._session), "post", side_effect=responses),
            patch("dumemeval.core.retry.time.sleep"),
        ):
            hit = a.search("q")
        assert hit["episodes"] == []

        with (
            patch.object(type(a._session), "post", return_value=_resp({"err": "bad"}, 400)),
            pytest.raises(Exception, match=r"400|HTTPError"),
        ):
            a.search("q")


class TestSnapshot:
    def test_snapshot_writes_ops_summary(self, tmp_path: Path) -> None:
        a = _make()
        a.setup(_task())
        rec = _Recorder()
        ctx: dict[str, Any] = {}
        with patch.object(type(a._session), "post", rec):
            session = SessionSpec(id=2, instruction="qa", memory_inject=True)
            a.inject(session, ctx)
            snap = a.snapshot(session, tmp_path)
        data = json.loads((snap / "everos_ops.json").read_text())
        assert data["project_id"] == a.project_id
        assert any(op["op"] == "search" for op in data["ops"])
