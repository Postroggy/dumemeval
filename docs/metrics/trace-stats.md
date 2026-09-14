# Trace 行为统计增强（tool call / 耗时 / LLM 次数）

- 状态：implemented
- 源码：`metrics/dimensions/trace_stats.py` · `pipeline/metrics_run.py`（接入点）
- 关联：`docs/metrics/trace.md` · `docs/architecture/run-artifacts.md`

## 问题

一次测评只报告四件事：采集率、空输出、错误率、是否调过 memory。用户要的
**tool call 分类统计、任务总耗时、LLM 调用次数、耗时占比**——数据都在
`trials/<task>__session_<n>/agent/trajectory.json`（Harbor ATIF 统一模型），
但框架没算。

## 通用性评估（决定范围）

| 指标 | 数据源 | 跨 runtime / memory 通用？ |
|---|---|---|
| tool call 数量 + 按 name 分类 | ATIF `step.tool_calls[].name` | ✅ 统一（Harbor 模型） |
| session 总耗时 | ATIF `step.timestamp`（ISO 8601 首尾差） | ✅ 统一 |
| LLM 调用次数 | ATIF `step.llm_call_count` | ✅ 统一 |
| 耗时占比（agent / tool / system 步） | 上述 timestamp 分组 | ✅ 统一 |
| memory search 时延 | adapter 合成时间戳 | ❌ 各 adapter 填法不一，值不可信 |
| memory 召回率 | search 结果 vs gold | ❌ 无统一 gold 口径，数据集相关 |

**结论**：只实现「来自 ATIF 统一模型」的通用统计。memory 时延/召回不纳入——
它们不是「无论谁都能统计」的，属于 adapter/数据集相关，不在本次范围。

## 方案

**模板方法 + 策略 + 组合**：

- `TraceStatCalculator`（抽象基类）：`calculate(trajectory) -> dict`，每个统计器一个策略
- 内置四个：
  - `ToolCallCounter`：tool 总数 + `{name: count}` 分类
  - `DurationStats`：总耗时、首尾时间戳
  - `LlmCallCounter`：`sum(step.llm_call_count)`
  - `PhaseDurationStats`：agent / tool / system 步耗时占比
- `TraceEnricher`（模板方法）：遍历 task 的每个 session → 读 `trial_dir/agent/trajectory.json` → 跑所有统计器 → 结果合并写进 `result.trace.details`

接入点：`pipeline/metrics_run.py` 的 `task_metrics`，在 `MetricsAggregator.run` 之前调用
`TraceEnricher`。纯计算，不改 SessionRunner、不改打分、不新增模型字段。

ATIF 解析复用 Harbor 模型（`harbor.models.trajectories.trajectory.Trajectory`），
与 `harbor_bridge._extract_agent_output` 同一来源，保证口径一致。

**读不到 trajectory 时**（mock / 失败 session / 文件缺失）：跳过该 session 的统计，
details 里记 `"stats_available": false`——「未测」≠「0」，与 GOVERNANCE 的
「勿过度解读」一致。

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 直接扩 `TraceResult` 加字段 | 新增字段要改 pydantic 模型 + 报告，且「每个统计器一个字段」会膨胀模型；details 已是 list[dict]，天然可容纳 |
| 在 `TraceCalculator` 里加统计 | 那会让一个计算器做两件事（体检 + 明细统计），违反 SRP；独立 enricher 可单独测试 |
| 从 `MemoryOp.timestamp` 算时延 | 该字段是 adapter 合成假时间（everos 用 `sess_idx*60_000`），不可信，通用统计不能建立在它上面 |

## 语义边界

- 统计来自 ATIF trajectory，**只在 Harbor 真跑时有效**；mock 没有真实轨迹。
- 失败 session 可能没有 trajectory，`stats_available=false`。
- tool call 按 `ToolCall.name` 分类，空 name 归 `"unknown"`。
- 耗时占比：agent 步（LLM 生成）vs tool 步（工具调用）vs system 步——只统计有有效
  timestamp 的步，解析失败忽略并计入「不可用」。
- 这些统计**不改任何官方口径和四维打分**，只追加 `trace.details` 的分析维度。

## 验证

- `tests/test_trace_stats.py`：用固定 ATIF fixture（含 tool_calls / llm_call_count /
  时间戳）断言各统计器输出；缺失文件 / mock 场景返回 `stats_available=false`。
- 全量 `make test` + `make lint`；`make example` mock 跑通（enricher 对 mock 无轨迹
  静默跳过）。

## 未完成

- memory 时延/召回率：需要 adapter 时间戳真实化 + 数据集相关 gold 口径，另开任务。
