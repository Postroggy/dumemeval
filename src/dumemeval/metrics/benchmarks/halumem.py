"""HaluMem 官方指标（操作级三阶段，对齐 HaluMem/eval/evaluation.py + eval_tools.py）。

官方判分（eval_tools.py 四个 prompt，逐字移植见 halumem_prompts.py）：
- Integrity：golden memory 是否被系统记忆库整体覆盖（score 2 全覆盖 / 1 部分 / 0 未提）
- Accuracy：单条 extracted memory 对 dialogue+golden 的支持度（2/1/0 + inclusion 布尔）
- Update：Correct / Hallucination / Omission / Other 四分类
- QA：Correct / Hallucination / Omission 三分类（含优先级规则：既有缺失又有编造 → Hallucination）

官方聚合（evaluation.py L202-281）：
- integrity recall(all/valid)：score==2 占比；None（解析失败）计入 all 分母、剔除 valid
- weighted：Σ(0.5·score·importance)/Σimportance
- interference_accuracy：score==0 计数占比（非 1−平均）
- target_accuracy：Σ(0.5·accuracy_score)/n

被测记忆库文本（extract_memories_str）来源优先级：
1. data["extracted_memories"]（官方 HF 结构）
2. MetricInput.memory_files（dumemeval 被测 memory 后端文件内容——本框架的语义映射）
3. 空 → 官方规则：integrity 直接记 0 分

注入 judge（bool）路径是二值简化（True→满分档），生产路径走懒加载官方 prompt。
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from .halumem_prompts import (
    EVALUATION_PROMPT_FOR_MEMORY_ACCURACY,
    EVALUATION_PROMPT_FOR_MEMORY_INTEGRITY,
    EVALUATION_PROMPT_FOR_QUESTION,
    EVALUATION_PROMPT_FOR_UPDATE_MEMORY,
)
from .locomo import JudgeFn

STAGE_EXTRACTION = "extraction"
STAGE_UPDATE = "update"
STAGE_QA = "qa"


def _parse_json_field(raw: str, key: str) -> str | None:
    """从 judge 输出提取 JSON 字段（官方 llm_request_for_json 的容错版）。"""
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            value = data.get(key)
            return str(value) if value is not None else None
        except (json.JSONDecodeError, ValueError):
            pass
    return None


class HaluMemCalculator(MetricCalculator):
    """HaluMem：三阶段指标（integrity recall / accuracy / update 分类 / QA 分类）。"""

    name: ClassVar[str] = "halumem"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm: Any = None
        self._llm_config = llm_config

    # ── 数据访问 ──────────────────────────────────────────────────────────

    def _extract_memories_str(self, inp: MetricInput, data: dict[str, Any]) -> str:
        """被测系统记忆库整体文本（官方 extract_memories_str）。"""
        extracted = data.get("extracted_memories")
        if isinstance(extracted, list) and extracted:
            return "\n".join(str(m) for m in extracted if m)
        if inp.memory_files:
            return "\n".join(inp.memory_files.values())
        return ""

    @staticmethod
    def _is_interference(mem: dict[str, Any]) -> bool:
        return str(mem.get("memory_source", "")) == "interference"

    # ── 主流程 ───────────────────────────────────────────────────────────

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        details: list[dict[str, Any]] = []
        extract_str = self._extract_memories_str(inp, data)

        # ── Integrity：golden memory 覆盖度（score 0/1/2，None=解析失败）──
        integrity: list[float | None] = []  # 非 interference
        interference: list[float | None] = []
        importance_sum = 0.0
        importance_scored = 0.0
        for mem in data.get("memory_points") or []:
            if not isinstance(mem, dict):
                continue
            if str(mem.get("is_update", "")) == "True":
                continue  # update 类走 update 阶段
            score = self._judge_integrity(extract_str, mem)
            if self._is_interference(mem):
                interference.append(score)
            else:
                integrity.append(score)
                imp = float(mem.get("importance", 1.0) or 1.0)
                importance_sum += imp
                if score is not None:
                    importance_scored += 0.5 * score * imp

        # ── Accuracy：extracted memory 支持度 ─────────────────────────────
        accuracy_scores: list[float | None] = []
        dialogue = str(data.get("dialogue", ""))
        golden_str = "\n".join(
            str(m.get("memory_content", ""))
            for m in (data.get("memory_points") or [])
            if isinstance(m, dict) and not self._is_interference(m)
        )
        for mem in data.get("extracted_memories") or []:
            if not isinstance(mem, str) or not mem.strip():
                continue
            accuracy_scores.append(self._judge_accuracy(dialogue, golden_str, mem))

        # ── Update / QA 分类 ──────────────────────────────────────────────
        update_counts = {"Correct": 0, "Hallucination": 0, "Omission": 0, "Other": 0}
        for upd in data.get("updates") or []:
            if isinstance(upd, dict):
                label = self._judge_update(extract_str, upd)
                update_counts[label] = update_counts.get(label, 0) + 1
        qa_counts = {"Correct": 0, "Hallucination": 0, "Omission": 0}
        for qa in data.get("qa") or []:
            if isinstance(qa, dict):
                label = self._judge_qa(qa, inp)
                qa_counts[label] = qa_counts.get(label, 0) + 1

        values: dict[str, float] = {}
        if integrity:
            valid = [s for s in integrity if s is not None]
            values["integrity_recall_all"] = sum(1.0 for s in valid if s == 2) / len(integrity)
            if valid:
                values["integrity_recall_valid"] = sum(1.0 for s in valid if s == 2) / len(valid)
        if importance_sum:
            values["integrity_weighted_recall"] = importance_scored / importance_sum
        if interference:
            values["interference_accuracy"] = sum(1.0 for s in interference if s == 0) / len(interference)
        if accuracy_scores:
            values["target_accuracy"] = sum(0.5 * s for s in accuracy_scores if s is not None) / len(
                accuracy_scores
            )
        total_update = sum(update_counts.values())
        if total_update:
            for label, count in update_counts.items():
                values[f"update_{label.lower()}_ratio"] = count / total_update
        total_qa = sum(qa_counts.values())
        if total_qa:
            for label, count in qa_counts.items():
                values[f"qa_{label.lower()}_ratio"] = count / total_qa
        details.append(
            {
                "integrity_count": len(integrity),
                "interference_count": len(interference),
                "accuracy_count": len(accuracy_scores),
                "update_counts": update_counts,
                "qa_counts": qa_counts,
                "extracted_memories_chars": len(extract_str),
            }
        )
        return MetricBundle(name=self.name, kind=self.kind, values=values, details=details)

    # ── 三阶段 judge（注入二值 / 懒加载官方 prompt）─────────────────────

    def _judge_integrity(self, extract_str: str, memory: dict[str, Any]) -> float | None:
        """官方：golden memory 是否被 extract_memories 整体覆盖 → 0/1/2。"""
        content = str(memory.get("memory_content", ""))
        if not content:
            return 0.0
        if not extract_str.strip():
            return 0.0  # 官方：空记忆库直接 0 分
        if self._judge is not None:
            return 2.0 if self._judge(extract_str, content, "integrity") else 0.0
        raw = self._llm_raw(
            EVALUATION_PROMPT_FOR_MEMORY_INTEGRITY.format(memories=extract_str, expected_memory_point=content)
        )
        score = _parse_json_field(raw, "score")
        return float(score) if score is not None else None

    def _judge_accuracy(self, dialogue: str, golden_str: str, candidate: str) -> float | None:
        """官方：单条 extracted memory 支持度 → 0/1/2。"""
        if self._judge is not None:
            return 2.0 if self._judge(candidate, golden_str, "accuracy") else 0.0
        raw = self._llm_raw(
            EVALUATION_PROMPT_FOR_MEMORY_ACCURACY.format(
                dialogue=dialogue, golden_memories=golden_str, candidate_memory=candidate
            )
        )
        score = _parse_json_field(raw, "accuracy_score")
        return float(score) if score is not None else None

    def _judge_update(self, extract_str: str, upd: dict[str, Any]) -> str:
        """官方四分类：Correct / Hallucination / Omission / Other。"""
        target = str(upd.get("memory_content", ""))
        original = "\n".join(str(m) for m in upd.get("memories_from_system", []) if m)
        if self._judge is not None:
            # 二值简化（测试路径）：True→Correct，False→Hallucination
            return "Correct" if self._judge(extract_str, target, "update") else "Hallucination"
        raw = self._llm_raw(
            EVALUATION_PROMPT_FOR_UPDATE_MEMORY.format(
                memories=extract_str, updated_memory=target, original_memory=original
            )
        )
        label = _parse_json_field(raw, "evaluation_result")
        return label if label in {"Correct", "Hallucination", "Omission", "Other"} else "Other"

    def _judge_qa(self, qa: dict[str, Any], inp: MetricInput) -> str:
        """官方三分类（含优先级：缺失+编造并存 → Hallucination）。"""
        question = str(qa.get("question", ""))
        answer = str(qa.get("answer", ""))
        key_points = str(qa.get("key_memory_points", "") or answer)
        pred = next((item.output for item in inp.outputs if item.query == question), "")
        if not pred:
            return "Omission"  # 官方：明说不知道/空 → Omission
        if self._judge is not None:
            return "Correct" if self._judge(pred, answer, question) else "Hallucination"
        raw = self._llm_raw(
            EVALUATION_PROMPT_FOR_QUESTION.format(
                question=question, reference_answer=answer, key_memory_points=key_points, response=pred
            )
        )
        label = _parse_json_field(raw, "evaluation_result")
        return label if label in {"Correct", "Hallucination", "Omission"} else "Omission"

    def _llm_raw(self, prompt: str) -> str:
        """懒加载 LLM judge，返回原始输出（官方 llm_request_for_json 对应物）。"""
        if self._llm is None:
            from ...verifier import make_llm_judge

            self._llm = make_llm_judge("task_success", self._llm_config)
        return str(self._llm.verify_with_prompt(prompt).raw)
