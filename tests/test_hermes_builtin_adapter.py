"""测试：Hermes 官方内置 memory（MEMORY.md / USER.md）适配器。

对齐 hermes-agent tools/memory_tool.py（MemoryStore）语义：
§ 分隔条目、add/replace/remove 唯一子串匹配、冻结快照格式、原子写盘。
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.adapters.hermes_builtin import HermesBuiltinMemoryAdapter
from dumemeval.adapters.hermes_format import (
    ENTRY_DELIMITER,
    parse_entries,
    render_block,
)
from dumemeval.adapters.registry import create_adapter
from dumemeval.models import EvalTask, MemorySpec, SessionSpec


def make_adapter(tmp_path: Path) -> HermesBuiltinMemoryAdapter:
    return HermesBuiltinMemoryAdapter(
        MemorySpec(
            name="hb",
            type="hermes_builtin",
            path=str(tmp_path / "memories"),
            config={"model": "test-model"},  # inject 生成 BYOK config 时必需；框架不预设厂商模型
        )
    )


def make_task() -> EvalTask:
    return EvalTask(name="t", sessions=[SessionSpec(id=1, instruction="x")])


class TestParseEntries:
    def test_empty(self) -> None:
        assert parse_entries("") == []
        assert parse_entries("  \n ") == []

    def test_single_entry(self) -> None:
        assert parse_entries("hello") == ["hello"]

    def test_multiple_stripped(self) -> None:
        raw = "first\n§\nsecond  \n§\nthird"
        assert parse_entries(raw) == ["first", "second", "third"]

    def test_dedup_preserves_order(self) -> None:
        raw = "a\n§\nb\n§\na"
        assert parse_entries(raw) == ["a", "b"]

    def test_empty_entries_skipped(self) -> None:
        raw = "a\n§\n\n§\nb"
        assert parse_entries(raw) == ["a", "b"]


class TestRenderBlock:
    def test_empty_returns_empty(self) -> None:
        assert render_block("memory", [], 2200) == ""

    def test_header_format(self) -> None:
        block = render_block("memory", ["a"], 2200)
        assert block.startswith("═" * 46 + "\n")
        assert "MEMORY (your personal notes) [0% — 1/2,200 chars]" in block

    def test_user_header(self) -> None:
        block = render_block("user", ["pref"], 1375)
        assert "USER PROFILE (who the user is)" in block

    def test_content_joined_by_delimiter(self) -> None:
        block = render_block("memory", ["a", "b"], 2200)
        assert f"a{ENTRY_DELIMITER}b" in block


class TestHermesBuiltinAdapter:
    def test_setup_creates_empty_dir(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        assert a.memory_dir.exists()
        assert list(a.memory_dir.iterdir()) == []  # 干净起点
        assert a.enabled_targets == {"memory", "user"}

    def test_add_writes_memory_md(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        r = a.add("User likes hiking", session_id=1)
        assert r["success"] is True
        content = (a.memory_dir / "MEMORY.md").read_text()
        assert content == "User likes hiking"
        ops = a.observe(SessionSpec(id=1, instruction=""))
        assert any(op.op == "add" for op in ops)

    def test_add_rejects_empty_duplicate(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        assert a.add("")["success"] is False
        assert a.add("x")["success"] is True
        r = a.add("x")
        assert r["success"] is False
        assert "already exists" in r["error"]

    def test_add_rejects_over_limit(self, tmp_path: Path) -> None:
        spec = MemorySpec(
            name="hb", type="hermes_builtin", path=str(tmp_path / "m"), config={"memory_limit": 10}
        )
        a = HermesBuiltinMemoryAdapter(spec)
        a.setup(make_task())
        r = a.add("this is a very long entry that exceeds the limit")
        assert r["success"] is False
        assert "exceed the limit" in r["error"]

    def test_replace_unique_substring(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.add("User likes hiking on weekends")
        r = a.replace("hiking", "User loves running")
        assert r["success"] is True
        assert a._load_entries("memory") == ["User loves running"]

    def test_replace_no_match(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.add("abc")
        r = a.replace("xyz", "new")
        assert r["success"] is False
        assert "No entry matched" in r["error"]

    def test_replace_multiple_match(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.add("alpha beta")
        a.add("gamma beta")
        r = a.replace("beta", "new")
        assert r["success"] is False
        assert "Multiple entries matched" in r["error"]

    def test_remove_unique_substring(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.add("entry one")
        a.add("entry two")
        r = a.remove("one")
        assert r["success"] is True
        assert a._load_entries("memory") == ["entry two"]

    def test_remove_no_match(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.add("abc")
        assert a.remove("zzz")["success"] is False

    def test_user_target_writes_user_md(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.add("Prefers mornings", target="user")
        assert (a.memory_dir / "USER.md").exists()
        assert a._load_entries("user") == ["Prefers mornings"]

    def test_disabled_target_rejected(self, tmp_path: Path) -> None:
        spec = MemorySpec(
            name="hb", type="hermes_builtin", path=str(tmp_path / "m"), config={"targets": ["memory"]}
        )
        a = HermesBuiltinMemoryAdapter(spec)
        a.setup(make_task())
        r = a.add("x", target="user")
        assert r["success"] is False
        assert "disabled" in r["error"]

    def test_snapshot_format_in_inject(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.add("fact one")
        a.add("fact two")
        ctx: dict[str, Any] = {}
        a.inject(SessionSpec(id=1, instruction=""), ctx)
        env = ctx["agent_env"]
        assert env["HERMES_MEMORY_DIR"] == str(a.memory_dir)
        snap = env["HERMES_MEMORY_SNAPSHOT"]
        assert "═" * 46 in snap
        assert "MEMORY (your personal notes)" in snap
        assert f"fact one{ENTRY_DELIMITER}fact two" in snap
        assert "USER PROFILE" not in snap  # user 无条目不渲染

    def test_seed_history_from_conversation_sessions(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        task = EvalTask(
            name="t",
            sessions=[SessionSpec(id=1, instruction="x")],
            data={
                "conversation_sessions": [
                    [{"speaker": "Caroline", "text": "went to support group on 7 May 2023"}],
                    [{"speaker": "Mel", "text": "painted a sunrise"}],
                ]
            },
        )
        a.seed_history(task)
        entries = a._load_entries("memory")
        assert "went to support group on 7 May 2023" in entries
        assert "painted a sunrise" in entries

    def test_seed_history_empty_skips(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.seed_history(EvalTask(name="t", sessions=[SessionSpec(id=1, instruction="x")]))
        assert a._load_entries("memory") == []

    def test_snapshot_copies_files(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.add("fact")
        snap = a.snapshot(SessionSpec(id=1, instruction=""), tmp_path / "snaps")
        assert (snap / "MEMORY.md").exists()
        assert (snap / "MEMORY.md").read_text() == "fact"

    def test_read_memory_files(self, tmp_path: Path) -> None:
        a = make_adapter(tmp_path)
        a.setup(make_task())
        a.add("fact", target="memory")
        a.add("pref", target="user")
        files = a.read_memory_files()
        assert set(files.keys()) == {"MEMORY.md", "USER.md"}
        assert "fact" in files["MEMORY.md"]
        assert "pref" in files["USER.md"]

    def test_registry_creates(self, tmp_path: Path) -> None:
        a = create_adapter(MemorySpec(name="hb", type="hermes_builtin", path=str(tmp_path / "m")))
        assert isinstance(a, HermesBuiltinMemoryAdapter)

    def test_roundtrip_multiline_entry(self, tmp_path: Path) -> None:
        """多行条目 round-trip（对齐 Hermes 的多行条目语义）。"""
        a = make_adapter(tmp_path)
        a.setup(make_task())
        multiline = "line1\nline2\nline3"
        a.add(multiline)
        assert a._load_entries("memory") == [multiline]
        # 写盘格式：单条目无分隔符
        assert (a.memory_dir / "MEMORY.md").read_text() == multiline
