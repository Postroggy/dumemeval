"""LoCoMo 数据集适配。

数据与指标口径：
- LoCoMo 数据：10 个长对话，每个 199 个 QA（question/answer/evidence/category）
- 指标：官方 stemmed F1（metrics.benchmarks.locomo）+ 按类 accuracy（category_mapping）
- 适配器只负责 build_tasks；evaluate 委托统一指标层

Source: https://github.com/snap-research/locomo
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...models import EvalTask, MemoryFact, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark


class LoCoMoQA(BaseModel):
    """LoCoMo 单个 QA。"""

    question: str
    answer: str | int | float = ""
    evidence: list[str] = Field(default_factory=list)
    category: int = 0
    options: dict[str, str] = Field(default_factory=dict)


class LoCoMoItem(BaseModel):
    """LoCoMo 单个对话（含多 session + QA）。"""

    sample_id: str | int = 0
    conversation: dict[str, Any] = Field(default_factory=dict)
    qa: list[LoCoMoQA] = Field(default_factory=list)


class LoCoMoData(BenchmarkData):
    """LoCoMo 类型化数据。"""

    items: list[LoCoMoItem] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> LoCoMoData:
        return cls(items=[LoCoMoItem.model_validate(item) for item in raw])


@register_benchmark
class LoCoMoAdapter(BenchmarkAdapter):
    """LoCoMo：长对话 memory QA 评测。"""

    name = "locomo"

    @property
    def data_type(self) -> type[BenchmarkData]:
        return LoCoMoData

    def build_tasks(
        self, data: BenchmarkData, subset: int | None = None, max_questions: int | None = None
    ) -> list[EvalTask]:
        """每个对话 → 一个 multi-session EvalTask。

        subset:        可选，只取前 N 个对话（smoke test 用小数据）。
        max_questions: 可选，每个对话只取前 N 题（进一步缩小 smoke 范围）。
        """
        if not isinstance(data, LoCoMoData):
            raise TypeError(f"Expected LoCoMoData, got {type(data)}")

        items = data.items[:subset] if subset else data.items

        tasks: list[EvalTask] = []
        for idx, item in enumerate(items):
            conv = item.conversation
            qa = item.qa[:max_questions] if max_questions else item.qa

            sessions: list[str] = []
            for key in sorted(conv.keys()):
                if key.startswith("session_") and isinstance(conv[key], list):
                    text = "\n".join(
                        f"{c.get('speaker', '')}: {c.get('text', '')}"
                        for c in conv[key]
                        if isinstance(c, dict)
                    )
                    if text:
                        sessions.append(text)

            if not sessions:
                continue

            gold_text = "\n".join(f"Q: {q.question}\nA: {q.answer}" for q in qa)
            facts = [MemoryFact(fact=str(q.answer), category="fact") for q in qa if str(q.answer)]

            ingest_sessions = [
                SessionSpec(
                    id=i + 1,
                    instruction=f"以下是对话的第 {i + 1} 部分，请阅读并记住重要信息：\n\n{session_text}",
                    memory_inject=True,
                )
                for i, session_text in enumerate(sessions)
            ]
            qa_sessions = [
                SessionSpec(
                    id=len(ingest_sessions) + j + 1,
                    instruction=(
                        "基于你记住的对话信息，只回答下面这一题。"
                        "直接给出简短答案，不要复述全部记忆、不要解释过程。\n\n"
                        f"Q: {q.question}"
                    ),
                    memory_inject=True,
                    query=q.question,
                )
                for j, q in enumerate(qa)
            ]

            task = EvalTask(
                name=f"locomo_{idx}",
                description=f"LoCoMo conversation {idx}",
                sessions=ingest_sessions + qa_sessions,
                memory_ground_truth="\n".join(f.fact for f in facts),
                task_ground_truth=gold_text,
                data={
                    "sample_id": item.sample_id,
                    "qa": [q.model_dump() for q in qa],
                    # Hermes 等 memory 后端的"历史对话灌入"数据源
                    "conversation_sessions": [
                        [
                            {"speaker": c.get("speaker", ""), "text": c.get("text", "")}
                            for c in conv.get(key, [])
                            if isinstance(c, dict)
                        ]
                        for key in sorted(conv.keys())
                        if key.startswith("session_") and isinstance(conv[key], list)
                    ],
                },
                benchmark="locomo",
            )
            tasks.append(task)
        return tasks

    def _judge_correct(self, pred: str, gold: str, question: str) -> bool:
        """LLM judge 判 CORRECT/WRONG（可被测试替换）。"""
        if self._judge is None:
            from ...verifier import make_llm_judge

            self._judge = make_llm_judge("memory_qa")
        verdict = self._judge.verify(pred, gold, question=question)
        return bool(verdict.is_pass)

    _judge: Any = None
