# MemoryAgentBench 怎么接到本仓库

- 状态：implemented
- 源码：`src/dumemeval/datasets/benchmarks/memoryagentbench.py`
- 官方代码（本机 Dataset 树）：
  - `conversation_creator.py` `get_chunks()`（约 L261-275）
  - `initialization.py` `_memorize_context_chunks`（约 L341-348）
  - `utils/eval_other_utils.py` `chunk_text_into_sentences`（约 L177-226）
- Source: https://github.com/HUST-AI-HYZ/MemoryAgentBench
- Paper: https://arxiv.org/pdf/2507.05257

## 问题

旧实现把整段 `context` 放进**一个** ingest session。那是错的。

官方不是一次把长文塞进 prompt：

1. `get_chunks()`：`chunk_text_into_sentences(context, chunk_size=…)`（data_conf 默认 4096）
2. 每个 chunk：`agent.send_message(chunk, memorizing=True)`
3. 再逐题问

README 里「inject once, query multiple times」的意思是：**一份长文对应多道题**，不是一次 ingest。

## 方案

本仓库没有官方那个 `send_message(..., memorizing=True)`。对应关系是：

- 每个 chunk → 一轮 ingest（instruction 只有这一块，让 agent 读完记住）
- 每道题 → 一轮 qa（`SessionSpec.query` 用题目原文）
- 一条 parquet 样本 → 一个 task（样本之间不共用 memory）
- 顺序：先 ingest 完，再 qa

`chunk_size` 走 `task.benchmark_options.chunk_size`，默认 4096。

切块跟官方函数对齐：nltk 断句（没有 punkt 就用 `(?<=[.!?])\s+`，评测过程不下载 punkt）；tiktoken `gpt-4o-mini` 数 token；一句超过上限就单独成块。

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 整段 context 一轮 session | 官方是逐块 `send_message`，测的是增量记忆，不是超长阅读 |
| 用字符数近似 token | chunk 边界对不上，全量分数没法跟官方比 |
| 运行时 `nltk.download('punkt')` | CI 和评测不能联网 |

## 语义边界

- 每块仍是一轮 Harbor session，不是直接调 mem0 `add()`。
- 官方部分 memory agent 用 `agent_chunk_size`；本仓库默认跟 data_conf 的 4096，要改用 `benchmark_options.chunk_size`。
- Recsys 和按 source 路由的指标没动。

## 未完成

- 官方 `AgentWrapper.send_message` 的 prompt 模板（`utils/templates.py`）没有抄进 instruction。
- 还没有拿全量 parquet 跟官方 runner 对 chunk 个数。
