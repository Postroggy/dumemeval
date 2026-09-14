"""测试：Quality 评测。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.metrics.dimensions.quality import QualityEvaluator
from dumemeval.models import EvalResult, MemoryFact


class TestQualityEvaluator:
    def test_rule_verifier_recall(self) -> None:
        """规则判分：memory 内容包含 ground truth fact 时 recall=1。"""
        qe = QualityEvaluator({"type": "rule"})
        result = EvalResult(task_name="t", memory_backend="m")
        memory_files = {"pref.md": "Alice likes latte without sugar\nAlice prefers window seat"}
        facts = [
            MemoryFact(fact="latte", category="preference"),
            MemoryFact(fact="window seat", category="preference"),
        ]
        qr = qe.evaluate(result, memory_files, facts)
        assert qr.recall == 1.0
        assert qr.precision == 1.0  # 单条记忆命中全部事实
        assert qr.hallucination_rate == 0.0
        assert qr.omission_rate == 0.0

    def test_rule_verifier_miss(self) -> None:
        """memory 缺少事实时 recall=0，omission=1。"""
        qe = QualityEvaluator({"type": "rule"})
        result = EvalResult(task_name="t", memory_backend="m")
        memory_files = {"pref.md": "Alice likes tea"}
        facts = [MemoryFact(fact="latte", category="preference")]
        qr = qe.evaluate(result, memory_files, facts)
        assert qr.recall == 0.0
        assert qr.omission_rate == 1.0

    def test_empty_ground_truth(self) -> None:
        """无 ground truth 时返回空结果。"""
        qe = QualityEvaluator({"type": "rule"})
        result = EvalResult(task_name="t", memory_backend="m")
        qr = qe.evaluate(result, {}, [])
        assert qr.recall == 0.0 and qr.precision == 0.0

    def test_partial_recall(self) -> None:
        """部分命中时 recall 为比例。"""
        qe = QualityEvaluator({"type": "rule"})
        result = EvalResult(task_name="t", memory_backend="m")
        memory_files = {"pref.md": "Alice likes latte"}
        facts = [
            MemoryFact(fact="latte", category="preference"),
            MemoryFact(fact="window seat", category="preference"),
        ]
        qr = qe.evaluate(result, memory_files, facts)
        assert qr.recall == 0.5
        assert qr.omission_rate == 0.5

    def test_hallucination_detected(self) -> None:
        """多余记忆文件（无关内容）降低 precision，hallucination > 0。"""
        qe = QualityEvaluator({"type": "rule"})
        result = EvalResult(task_name="t", memory_backend="m")
        memory_files = {
            "good.md": "Alice likes latte",
            "noise.md": "random unrelated note about weather",
        }
        facts = [MemoryFact(fact="latte", category="preference")]
        qr = qe.evaluate(result, memory_files, facts)
        assert qr.recall == 1.0
        assert qr.precision == 0.5  # 2 条记忆只有 1 条命中
        assert qr.hallucination_rate == 0.5

    def test_multi_memory_files(self) -> None:
        """多记忆文件时 precision = 命中数 / 记忆数。"""
        qe = QualityEvaluator({"type": "rule"})
        result = EvalResult(task_name="t", memory_backend="m")
        memory_files = {
            "a.md": "latte",
            "b.md": "window seat",
            "c.md": "irrelevant",
        }
        facts = [
            MemoryFact(fact="latte", category="preference"),
            MemoryFact(fact="window seat", category="preference"),
        ]
        qr = qe.evaluate(result, memory_files, facts)
        assert qr.recall == 1.0
        assert qr.precision == 2 / 3


class TestQualityProbe:
    def _write_session(self, tmp_path: Path, lines: list[str]) -> Path:
        p = tmp_path / "session.jsonl"
        p.write_text("\n".join(lines) + "\n")
        return p

    def test_extract_memory_write(self, tmp_path: Path) -> None:
        """Write 工具写 memory 文件 → memory_write 事件。"""
        from dumemeval.metrics.core.probe import QualityProbe

        p = self._write_session(
            tmp_path,
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "s1",
                        "timestamp": 123.0,
                        "message": {
                            "role": "assistant",
                            "tool_use": {
                                "name": "Write",
                                "input": {
                                    "file_path": "/app/memory/alice.md",
                                    "content": "# Alice likes latte",
                                },
                            },
                        },
                    }
                )
            ],
        )
        events = QualityProbe().extract_from_session(str(p))
        assert len(events) == 1
        assert events[0]["type"] == "memory_write"
        assert events[0]["session_id"] == "s1"

    def test_extract_memory_read(self, tmp_path: Path) -> None:
        """Read 工具读 memory 文件 → memory_read 事件。"""
        from dumemeval.metrics.core.probe import QualityProbe

        p = self._write_session(
            tmp_path,
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "tool_use": {"name": "Read", "input": {"file_path": "/app/memory/alice.md"}},
                        },
                    }
                )
            ],
        )
        events = QualityProbe().extract_from_session(str(p))
        assert len(events) == 1
        assert events[0]["type"] == "memory_read"

    def test_extract_mention(self, tmp_path: Path) -> None:
        """用户消息提到 memory 关键词 → memory_mention 事件。"""
        from dumemeval.metrics.core.probe import QualityProbe

        p = self._write_session(
            tmp_path,
            [
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": "请记住我的偏好：咖啡只喝拿铁"},
                    }
                )
            ],
        )
        events = QualityProbe().extract_from_session(str(p))
        assert len(events) == 1
        assert events[0]["type"] == "memory_mention"
        assert "拿铁" in events[0]["content"]

    def test_non_memory_ignored(self, tmp_path: Path) -> None:
        """普通消息（无 memory 关键词/路径）→ 无事件。"""
        from dumemeval.metrics.core.probe import QualityProbe

        p = self._write_session(
            tmp_path,
            [json.dumps({"type": "user", "message": {"role": "user", "content": "你好"}})],
        )
        assert QualityProbe().extract_from_session(str(p)) == []

    def test_missing_file(self, tmp_path: Path) -> None:
        from dumemeval.metrics.core.probe import QualityProbe

        assert QualityProbe().extract_from_session(str(tmp_path / "nope.jsonl")) == []

    def test_scan_dir(self, tmp_path: Path) -> None:
        """扫描目录聚合事件。"""
        from dumemeval.metrics.core.probe import QualityProbe

        (tmp_path / "s1.jsonl").write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "tool_use": {"name": "Write", "input": {"file_path": "/app/memory/a.md"}},
                    },
                }
            )
            + "\n"
        )
        (tmp_path / "s2.jsonl").write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": "记住这个"},
                }
            )
            + "\n"
        )
        events = QualityProbe().scan_dir(str(tmp_path))
        assert len(events) == 2


class TestQualityEvaluatorProbeIntegration:
    def test_probe_events_merged_into_judging(self) -> None:
        """probe_events 的 memory_write 内容合并进判分输入。"""
        qe = QualityEvaluator({"type": "rule"})
        result = EvalResult(task_name="t", memory_backend="m")
        # memory 文件为空，但探测到写入事件包含事实
        memory_files: dict[str, str] = {}
        facts = [MemoryFact(fact="latte", category="preference")]
        probe_events = [{"type": "memory_write", "content": "Alice likes latte without sugar"}]
        qr = qe.evaluate(result, memory_files, facts, probe_events=probe_events)
        assert qr.recall == 1.0  # 探测内容命中

    def test_no_probe_events_no_change(self) -> None:
        """无 probe_events 时行为不变。"""
        qe = QualityEvaluator({"type": "rule"})
        result = EvalResult(task_name="t", memory_backend="m")
        memory_files = {"a.md": "Alice likes tea"}
        facts = [MemoryFact(fact="latte", category="preference")]
        qr = qe.evaluate(result, memory_files, facts)
        assert qr.recall == 0.0
