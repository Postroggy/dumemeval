"""memsim / MemDaily 官方指标（确定性判分）。

来源：benchmarks/conversation/memsim/benchmark/TimeFlow.py：
- accuracy = agent_res['answer'] == std['ground_truth']（选项字母 exact match，L25）
- recall   = get_recall(res, std['target_step_id'])（L9-16）：
    agent 检索出的 step id 与 target_step_id 集合的命中率（ct/len(std_set)）
- target_step_id 是字符串化的 python list（如 "[0, 4]"），需解析
- 6 类问题（simple/conditional/comparative/aggregative/post_processing/noisy）
  共用同一套指标，官方按 QA 类型聚合

无 LLM judge。官方用 10 次重复取 mean±std，我们报单次 mean
（``execution.trials`` 多次 attempts 尚未实现，见 Roadmap）。
"""

from __future__ import annotations

import ast
import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind

_STEP_ID_RE = re.compile(r"\d+")


def parse_step_ids(raw: Any) -> list[int]:
    """把 "[0, 4]" / "[0]" / 字符串列表解析成 int 列表。"""
    if isinstance(raw, list):
        return [int(x) for x in raw]
    text = str(raw or "")
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, list):
            return [int(x) for x in parsed]
    except (ValueError, SyntaxError):
        pass
    return [int(x) for x in _STEP_ID_RE.findall(text)]


def recall_at_step_ids(retrieved: Any, target: Any) -> float:
    """官方 get_recall：命中数 / target 集合大小。"""
    res = set(parse_step_ids(retrieved))
    std_set = set(parse_step_ids(target))
    if not std_set:
        return 0.0
    return len(res & std_set) / len(std_set)


def memsim_accuracy(pred_answer: str, ground_truth: str) -> float:
    """官方 cal_metrics：选项字母 exact match（无容错）。"""
    return 1.0 if pred_answer == ground_truth else 0.0


class MemSimCalculator(MetricCalculator):
    """MemDaily：accuracy（选项字母）+ recall@step（检索命中率）。"""

    name: ClassVar[str] = "memsim"
    kind: ClassVar[MetricKind] = "benchmark"

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        qas = data.get("qa") or []
        by_type: dict[str, list[dict[str, float]]] = {}
        details: list[dict[str, Any]] = []
        n = 0
        for idx, qa in enumerate(qas):
            if not isinstance(qa, dict):
                continue
            n += 1
            query = str(qa.get("question") or "")
            qtype = str(qa.get("type") or "unknown")
            ground_truth = str(qa.get("ground_truth") or "")
            target = qa.get("target_step_id") or ""
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output
            acc = memsim_accuracy(pred, ground_truth)
            recall = recall_at_step_ids(pred, target) if pred else 0.0
            by_type.setdefault(qtype, []).append({"accuracy": acc, "recall": recall})
            details.append(
                {
                    "idx": idx,
                    "type": qtype,
                    "ground_truth": ground_truth,
                    "target_step_id": target,
                    "predicted": pred[:200],
                    "accuracy": acc,
                    "recall": recall,
                }
            )

        values: dict[str, float] = {"accuracy": 0.0, "recall": 0.0}
        if n:
            accs = [d["accuracy"] for vs in by_type.values() for d in vs]
            recs = [d["recall"] for vs in by_type.values() for d in vs]
            values["accuracy"] = sum(accs) / n
            values["recall"] = sum(recs) / n
        by_category: dict[str, dict[str, float]] = {}
        for qtype, rows in by_type.items():
            by_category[qtype] = {
                "accuracy": sum(r["accuracy"] for r in rows) / len(rows) if rows else 0.0,
                "recall": sum(r["recall"] for r in rows) / len(rows) if rows else 0.0,
                "count": float(len(rows)),
            }
            values[f"accuracy_{qtype}"] = by_category[qtype]["accuracy"]
            values[f"recall_{qtype}"] = by_category[qtype]["recall"]
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )
