"""MemoryAgentBench 数据集适配（ICLR 2026，四能力）。

数据：Dataset/data/MemoryAgentBench/data/*.parquet（4 文件，共 146 条 context）
官方 ingest（conversation_creator.get_chunks + initialization._memorize_context_chunks）：
  context → chunk_text_into_sentences(chunk_size=4096) → 每个 chunk
  ``agent.send_message(chunk, memorizing=True)`` → 再逐 question 提问。
本仓库映射：每个 chunk 一个 ingest session，每题一个 qa session
（先全部 memorize，再全部提问）。禁止把整段 context 塞进一条 instruction。
指标：按 source 路由（substring_exact_match / exact_match / Recall@5 / LLM judge）

Source: https://github.com/HUST-AI-HYZ/MemoryAgentBench
Paper: https://arxiv.org/pdf/2507.05257
"""

from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.benchmarks.locomo import JudgeFn
from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark

# 官方 data_conf/*.yaml 的 chunk_size；conversation_creator 默认跟 dataset 配置
DEFAULT_CHUNK_SIZE = 4096
# 官方 chunk_text_into_sentences 默认 tokenizer
_OFFICIAL_TOKENIZER_MODEL = "gpt-4o-mini"


class MemoryAgentBenchSample(BaseModel):
    """单条 context + 多组 QA。"""

    context: str = ""
    questions: list[str] = Field(default_factory=list)
    answers: list[list[str]] = Field(default_factory=list)
    source: str = ""


class MemoryAgentBenchData(BenchmarkData):
    samples: list[MemoryAgentBenchSample] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoryAgentBenchData:
        samples: list[MemoryAgentBenchSample] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata") or {}
            if not isinstance(meta, dict):
                meta = {}
            samples.append(
                MemoryAgentBenchSample(
                    context=str(item.get("context", "")),
                    questions=[str(q) for q in (item.get("questions") or [])],
                    answers=[
                        list(a) if isinstance(a, list) else [str(a)] for a in (item.get("answers") or [])
                    ],
                    source=str(meta.get("source", "")),
                )
            )
        return cls(samples=samples)

    @staticmethod
    def load_parquet_dir(data_dir: str | Path) -> MemoryAgentBenchData:
        """加载目录下所有 *.parquet。"""
        import pyarrow.parquet as pq

        rows: list[dict[str, Any]] = []
        for path in sorted(glob.glob(str(Path(data_dir) / "*.parquet"))):
            rows.extend(pq.read_table(path).to_pylist())
        return MemoryAgentBenchData.from_raw(rows)


def chunk_text_into_sentences(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    model_name: str = _OFFICIAL_TOKENIZER_MODEL,
) -> list[str]:
    """对齐官方 ``chunk_text_into_sentences``（eval_other_utils.py L177-226）。

    句切优先 nltk punkt；未安装时用 ``(?<=[.!?])\\s+`` 回退（评测禁止运行期下载）。
    token 计数用 tiktoken ``encoding_for_model(gpt-4o-mini)``，与官方默认一致。
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    stripped = (text or "").strip()
    if not stripped:
        return []

    try:
        import nltk

        sentences = [s.strip() for s in nltk.sent_tokenize(stripped) if s.strip()]
    except (LookupError, ImportError, OSError):
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", stripped) if s.strip()]
    if not sentences:
        sentences = [stripped]

    import tiktoken

    try:
        encoding = tiktoken.encoding_for_model(model_name)
    except KeyError:
        encoding = tiktoken.encoding_for_model(_OFFICIAL_TOKENIZER_MODEL)

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        n_tokens = len(encoding.encode(sentence, allowed_special={"<|endoftext|>"}))
        if current and current_tokens + n_tokens > chunk_size:
            chunks.append(" ".join(current))
            current = [sentence]
            current_tokens = n_tokens
        else:
            current.append(sentence)
            current_tokens += n_tokens
    if current:
        chunks.append(" ".join(current))
    return chunks


@register_benchmark
class MemoryAgentBenchAdapter(BenchmarkAdapter):
    name = "memoryagentbench"

    def __init__(self, judge: JudgeFn | None = None):
        self._judge = judge

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoryAgentBenchData

    def build_tasks(
        self,
        data: BenchmarkData,
        subset: int | None = None,
        max_questions: int | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> list[EvalTask]:
        """每个 context → 一个 EvalTask：先按官方粒度逐 chunk ingest，再逐题 qa。"""
        if not isinstance(data, MemoryAgentBenchData):
            raise TypeError(f"Expected MemoryAgentBenchData, got {type(data)}")
        samples = data.samples[:subset] if subset else data.samples
        tasks: list[EvalTask] = []
        for idx, sample in enumerate(samples):
            if not sample.questions:
                continue
            questions = sample.questions[:max_questions] if max_questions else sample.questions
            answers = sample.answers[:max_questions] if max_questions else sample.answers
            chunks = chunk_text_into_sentences(sample.context, chunk_size=chunk_size)
            if not chunks and sample.context.strip():
                chunks = [sample.context.strip()]
            ingest_sessions = [
                SessionSpec(
                    id=i + 1,
                    instruction=(
                        f"以下是文档的第 {i + 1}/{len(chunks)} 部分，请阅读并记住重要信息"
                        "（后续问题需要基于全部已读部分回答）：\n\n"
                        f"{chunk}"
                    ),
                    memory_inject=True,
                )
                for i, chunk in enumerate(chunks)
            ]
            qa_sessions = [
                SessionSpec(
                    id=len(ingest_sessions) + j + 1,
                    instruction=(
                        "基于你记住的文档内容，只回答下面这一题。"
                        "直接给出简短答案，不要复述全部记忆、不要解释过程。\n\n"
                        f"Q: {q}"
                    ),
                    memory_inject=True,
                    query=q,
                )
                for j, q in enumerate(questions)
            ]
            tasks.append(
                EvalTask(
                    name=f"memoryagentbench_{idx}",
                    description=f"MemoryAgentBench {sample.source} #{idx}",
                    sessions=ingest_sessions + qa_sessions,
                    data={
                        "samples": [
                            {
                                "source": sample.source,
                                "questions": questions,
                                "answers": answers,
                                "n_chunks": len(chunks),
                                "chunk_size": chunk_size,
                            }
                        ]
                    },
                    benchmark="memoryagentbench",
                )
            )
        return tasks
