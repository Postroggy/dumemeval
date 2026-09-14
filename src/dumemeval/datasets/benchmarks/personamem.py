"""PersonaMem 数据集适配（COLM 2025，用户画像 MCQ）。

数据：Dataset/data/PersonaMem/（questions_{32k,128k,1M}.csv + shared_contexts_*.jsonl）
官方指标（PersonaMem/inference.py extract_answer）：
- MCQ 选项字母匹配 accuracy（确定性，无 LLM judge）
- 按 7 类 question_type 分桶

组织：每个 persona（shared_context_id）→ 一个 EvalTask：
  - session 1：注入该 persona 的完整 context（shared_contexts 对应条目，
    截断到 end_index_in_shared_context，与官方一致）
  - session 2..N：每个问题一轮（user_question_or_message 原文）

Source: https://huggingface.co/datasets/bowen-upenn/PersonaMem
Paper: https://arxiv.org/abs/2504.14225
"""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.personamem import is_correct
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class PersonaMemQuestion(BaseModel):
    """单条 MCQ 问题（来自 questions CSV）。"""

    question_id: str = ""
    question_type: str = ""
    topic: str = ""
    user_question_or_message: str = ""
    correct_answer: str = ""
    all_options: list[str] = Field(default_factory=list)
    shared_context_id: str = ""
    end_index_in_shared_context: int | None = None
    groundtruth_info: str = ""


class PersonaMemData(BenchmarkData):
    """PersonaMem 类型化数据（按 shared_context 分组）。"""

    questions: list[PersonaMemQuestion] = Field(default_factory=list)
    contexts: dict[str, str] = Field(default_factory=dict)  # shared_context_id -> 完整 context 文本

    @classmethod
    def from_raw(cls, raw: Any) -> PersonaMemData:
        """raw: dict{"questions": list[dict], "contexts": dict[str, str]}。"""
        if not isinstance(raw, dict):
            raise TypeError(f"Expected dict with questions/contexts, got {type(raw)}")
        questions = [PersonaMemQuestion.model_validate(q) for q in raw.get("questions", [])]
        contexts = {str(k): str(v) for k, v in raw.get("contexts", {}).items()}
        return cls(questions=questions, contexts=contexts)


def _parse_all_options(raw: str) -> list[str]:
    """all_options 列兼容两种格式：JSON 数组字符串 和 CSV 内嵌转义引号。"""
    if not raw:
        return []
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (ValueError, SyntaxError):
        pass
    return []


@register_benchmark
class PersonaMemAdapter(BenchmarkAdapter):
    name = "personamem"

    @property
    def data_type(self) -> type[BenchmarkData]:
        return PersonaMemData

    @staticmethod
    def load_csv(path: str | Path, contexts_path: str | Path) -> PersonaMemData:
        """从 questions CSV + shared_contexts jsonl 直接加载。"""
        with Path(path).open() as f:
            rows = list(csv.DictReader(f))
        questions: list[PersonaMemQuestion] = []
        for row in rows:
            end = row.get("end_index_in_shared_context", "")
            questions.append(
                PersonaMemQuestion(
                    question_id=row.get("question_id", ""),
                    question_type=row.get("question_type", ""),
                    topic=row.get("topic", ""),
                    user_question_or_message=row.get("user_question_or_message", ""),
                    correct_answer=row.get("correct_answer", ""),
                    all_options=_parse_all_options(row.get("all_options", "")),
                    shared_context_id=row.get("shared_context_id", ""),
                    end_index_in_shared_context=int(end) if end.strip().isdigit() else None,
                    groundtruth_info=row.get("groundtruth_info", ""),
                )
            )
        contexts: dict[str, str] = {}
        for line in Path(contexts_path).read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            for cid, messages in entry.items():
                # 首条 system 消息含完整 persona；context 文本 = 全部消息拼接
                parts = []
                for msg in messages:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    parts.append(f"{role}: {content}" if role else str(content))
                contexts[str(cid)] = "\n".join(parts)
        return PersonaMemData(questions=questions, contexts=contexts)

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, PersonaMemData):
            raise TypeError(f"Expected PersonaMemData, got {type(data)}")
        # 按 shared_context_id 分组（一个 persona 一个任务）
        by_context: dict[str, list[PersonaMemQuestion]] = {}
        for q in data.questions:
            by_context.setdefault(q.shared_context_id or "no_context", []).append(q)

        tasks: list[EvalTask] = []
        for cid, qs in by_context.items():
            if not qs:
                continue
            # context 截断（与官方一致：context[:end_index]）
            context_text = data.contexts.get(cid, "")
            if qs[0].end_index_in_shared_context is not None:
                context_text = context_text[: qs[0].end_index_in_shared_context]
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"请阅读并记住以下用户画像和对话历史，后续问题需要基于它回答：\n\n{context_text}",
                    memory_inject=True,
                )
            ]
            for i, q in enumerate(qs, start=2):
                sessions.append(
                    SessionSpec(
                        id=i,
                        instruction=q.user_question_or_message,
                        memory_inject=True,
                        query=q.user_question_or_message,
                    )
                )
            tasks.append(
                EvalTask(
                    name=f"personamem_{qs[0].shared_context_id[:8]}",
                    description=f"PersonaMem persona {qs[0].shared_context_id[:8]}（{len(qs)} 题）",
                    sessions=sessions,
                    data={
                        "questions": [
                            {
                                "question": q.user_question_or_message,
                                "correct_answer": q.correct_answer,
                                "question_type": q.question_type,
                                "all_options": q.all_options,
                            }
                            for q in qs
                        ],
                        "persona_id": cid,
                    },
                    benchmark="personamem",
                )
            )
        return tasks


# 供测试直接复用判分函数
__all__ = ["PersonaMemAdapter", "PersonaMemData", "PersonaMemQuestion", "is_correct"]
