# Trace：Agent 行为体检

- 状态：implemented
- 源码：`src/dumemeval/metrics/dimensions/trace.py`
- 指标 kind：`trace`（横切第四维度，每场评测都算）

## 问题

业务问「agent 的 trace 正规吗」。此前框架有 trajectory 和 memory_ops 数据，但**没有任何指标去看它们**，于是两类失败会静默通过：

- trajectory 没采集到 → `observation` 为空 → 依赖输出的 benchmark 分数全是假 0，报告看起来只是「分数低」
- **memory 配了但 agent 一次没调** → `utility.success_rate` 照样可能是 1.0

## 方案

不新造机制：加 `MetricKind = "trace"` + `TraceCalculator`，复用 `MetricsAggregator` / `_apply_bundle` / 报告渲染 / compare 的 diff 能力。

指标全部来自已采集数据（`session_outcomes` + `memory_ops`），不引入新探测通道：

| 指标 | 回答 |
|---|---|
| `trace_captured_rate` | trajectory 采到了吗（0 = 依赖输出的分数全是假 0） |
| `empty_output_rate` | agent 有没有空跑 |
| `error_rate` | 跑挂了几个 session |
| `memory_tool_used` | **agent 真的读写过 memory 吗** |
| `memory_write_ops` / `memory_read_ops` | 记了多少、取了多少 |

**关键判定**：`setup` / `inject` / `snapshot` 是框架动作，**不计入** `memory_tool_used`；只有 `add` / `replace` / `remove` / `search` 这类 agent 侧读写才算。否则「memory 配了但 agent 一次没调」会被伪装成「用了」——这正是业务最关心的失败模式，已用测试锁死。

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 独立模块（不进 metrics 层） | 会绕过 aggregator，失去 compare 直接 diff trace 指标的能力 |
| 挂在 Utility 里 | 「任务成功没」和「行为是否正规」是两个问题，混在一维会互相掩盖 |
| 新增探测通道（解析容器日志） | 现有数据已足够回答核心问题；加通道会让 adapter 贡献者多一份负担 |
| `memory_tool_used` 统计所有 memory_ops | 框架的 inject/snapshot 每次必然发生，指标会恒为 true，失去判别力 |

## 语义边界

- **只看有没有，不看用得对不对**：`memory_tool_used=true` 不代表 agent 记的内容有用——那是 Quality 的职责
- `error_rate` 统计的是 session 级失败（含 `success=false`），不是 agent 内部的工具调用失败
- `trace_captured_rate=1.0` 只说明 observation 非空，不保证内容有意义

## 未完成

- turn 溢出（agent 跑到 max_turns 上限）
- 重复动作 / 死循环检测
- 输出格式漂移（要求 JSON 却返回散文）
- memory 写入内容与任务的相关性（这块偏 Quality，需要设计边界）
