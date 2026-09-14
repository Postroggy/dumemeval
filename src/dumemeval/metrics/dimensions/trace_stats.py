"""Trace 行为统计增强：从 ATIF trajectory 提取通用行为统计。

设计（docs/metrics/trace-stats.md）：
- ``TraceStatCalculator``（策略）：一个统计器算一项，独立可测
- ``TraceEnricher``（模板方法）：遍历 session → 读 trajectory → 跑全部统计器
  → 合并进 ``result.trace.details``
- 只依赖 ATIF 统一字段（steps[].tool_calls/llm_call_count/timestamp/source），
  跨 runtime 通用；不碰 memory 时延/召回（那依赖 adapter 时间戳 / 数据集
  gold 口径，不属于通用统计）
- 解析用纯 dict（不依赖 Harbor 模型类），测试可用 dict fixture
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ...models import EvalResult, EvalTask

logger = logging.getLogger(__name__)

# 与 harbor_bridge 同源的 ATIF trajectory 相对路径
TRAJECTORY_RELATIVE = "agent/trajectory.json"


def _steps(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    steps = trajectory.get("steps") or []
    return [s for s in steps if isinstance(s, dict)]


class TraceStatCalculator(ABC):
    """一个行为统计器（策略）：从 ATIF trajectory 算一项统计。"""

    name: str = ""

    @abstractmethod
    def calculate(self, trajectory: dict[str, Any]) -> dict[str, Any]:
        """输入 trajectory dict，返回统计 dict。"""


class ToolCallCounter(TraceStatCalculator):
    """tool call 总数 + 按 name 分类。"""

    name = "tool_calls"

    def calculate(self, trajectory: dict[str, Any]) -> dict[str, Any]:
        counts: Counter[str] = Counter()
        for step in _steps(trajectory):
            for call in step.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                name = str(call.get("name") or "unknown").strip() or "unknown"
                counts[name] += 1
        return {"total": int(sum(counts.values())), "by_tool": dict(counts)}


class LlmCallCounter(TraceStatCalculator):
    """LLM 调用次数（ATIF step.llm_call_count 之和）。"""

    name = "llm_calls"

    def calculate(self, trajectory: dict[str, Any]) -> dict[str, Any]:
        total = sum(int(step.get("llm_call_count") or 0) for step in _steps(trajectory))
        return {"total": total}


def _parse_iso(value: str | None) -> datetime | None:
    """解析 ISO 8601 时间戳；失败返回 None（不算入统计）。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class DurationStats(TraceStatCalculator):
    """session 总耗时（首尾有效 timestamp 之差，秒）。"""

    name = "duration"

    def calculate(self, trajectory: dict[str, Any]) -> dict[str, Any]:
        times: list[datetime] = []
        for step in _steps(trajectory):
            ts = _parse_iso(step.get("timestamp"))
            if ts is not None:
                times.append(ts)
        if len(times) < 2:
            return {"seconds": None, "start": None, "end": None}
        start, end = min(times), max(times)
        return {
            "seconds": round((end - start).total_seconds(), 3),
            "start": start.isoformat(),
            "end": end.isoformat(),
        }


class PhaseDurationStats(TraceStatCalculator):
    """耗时占比：按 step.source（agent / tool / system）分组。

    占比 = 该组耗时 / 总耗时；无有效时间戳时组记 None。
    """

    name = "phase_duration"

    def calculate(self, trajectory: dict[str, Any]) -> dict[str, Any]:
        buckets: dict[str, list[datetime]] = {}
        for step in _steps(trajectory):
            ts = _parse_iso(step.get("timestamp"))
            if ts is None:
                continue
            source = str(step.get("source") or "unknown")
            buckets.setdefault(source, []).append(ts)

        spans: dict[str, float] = {}
        for source, times in buckets.items():
            if len(times) >= 2:
                spans[source] = (max(times) - min(times)).total_seconds()

        total = sum(spans.values())
        if total <= 0:
            return {"total_seconds": None, "by_source": spans}
        return {
            "total_seconds": round(total, 3),
            "by_source": {k: round(v / total, 4) for k, v in spans.items()},
        }


_BUILTIN_STATS: tuple[type[TraceStatCalculator], ...] = (
    ToolCallCounter,
    LlmCallCounter,
    DurationStats,
    PhaseDurationStats,
)


class TraceEnricher:
    """模板方法：把通用行为统计写进 ``result.trace.details``。

    每个 session 读 ``trial_dir/agent/trajectory.json``（ATIF）；读不到
    （mock / 失败 / 文件缺失）跳过，details 里记 ``stats_available: false``——
    「未测」≠「0」。
    """

    def __init__(self, calculators: list[TraceStatCalculator] | None = None):
        self.calculators = calculators or [cls() for cls in _BUILTIN_STATS]

    def enrich(self, task: EvalTask, result: EvalResult) -> None:
        details = [d for d in result.trace.details if "stats" not in d] if result.trace else []
        for rec in result.session_outcomes:
            trial_dir = rec.get("trial_dir")
            trajectory = self._load_trajectory(trial_dir) if trial_dir else None
            entry: dict[str, Any] = {"session_id": rec.get("session_id")}
            if trajectory is None:
                entry["stats_available"] = False
            else:
                entry["stats_available"] = True
                for calc in self.calculators:
                    entry[calc.name] = calc.calculate(trajectory)
            details.append(entry)

        if result.trace is not None:
            result.trace.details = details

    @staticmethod
    def _load_trajectory(trial_dir: str) -> dict[str, Any] | None:
        """读并解析 ATIF trajectory（纯 dict）；任何失败返回 None（不伪造）。"""
        path = Path(trial_dir) / TRAJECTORY_RELATIVE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else None
        except Exception:
            logger.exception("解析 trajectory.json 失败: %s", path)
            return None
