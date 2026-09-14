# 设计评测：单 skill vs 多 skill 拓扑

> 沉淀自 Hermes 生产 trace 分析实战。参考 Datadog agent-observability（8-skill 拓扑）与
> Microsoft AgentRx（pipeline + --stage）。记录为什么本 skill 采用「单 skill + 分段执行」。

## 参考项目要点

- **Datadog agent-observability**：8 个 skill（replay/session-classify/trace-rca/eval-bootstrap/eval-pipeline/experiment-analyzer…）。
  每个 skill 对应一个**独立用户意图**（重放某条 trace ≠ 根因分析 ≠ 构建 eval 管道）。所以拆开合理。
- **AgentRx**：单管道 `Raw logs → Trajectory IR → Invariants → Checker → Judge → Reports`，
  各 stage 可独立运行（`--stage`），但共用一套 IR。

## 我们的场景特征

- 意图**单一**：批量 trace → memory 行为分析 → 结论报告。不是一个生态的多个入口。
- 流程**分阶段**：收集→组织→机制→画像→深度→验证→结论→产物，各阶段可复用、可跳过。

## 两种设计的对比

| 维度 | A. 单 skill（本方案） | B. 多 skill 拓扑（Datadog 风格） |
|---|---|---|
| 触发清晰度 | 1 个触发点，命中即进全流程 | 每个 skill 需各自触发条件，用户要选对入口 |
| 覆盖度 | 8 阶段全覆盖，references 分工 | 每 skill 只覆盖一段，需人工拼接 |
| 可执行性 | `analyze.py profile/memory/report` 一条命令链 | 每 skill 自带脚本，跨 skill 传参靠约定 |
| 可复算性 | 统一 `stats.json`（同目录累积） | 各 skill 各自输出，合并口径易漂移 |
| 可维护性 | references 分离，SKILL.md 简短 | 文件数多，维护成本高 |
| 调用成本 | 1 次 `/trace-memory-analysis` 进全流程；`--phase` 分段 | 多次调用 + 记住哪个 skill 做哪段 |
| 适用性 | 单一意图的工作流 | 多意图、生态型平台 |

## 实测

- **引擎**：`scripts/analyze.py` 在真实数据上验证 —— Batch1（200 会话扁平 tools 格式）、
  Batch2（280 会话嵌套 tools 格式）均产出正确指标（938 调用 / 73.7% 失败率 / 超限 571 /
  重复 14 / 热条目 95），与人工深挖结论一致。
- **踩坑修正**：tools 名称提取兼容扁平/嵌套格式（实测发现并修复）；tools 字段缺失与"无
  memory 工具"三态区分。

## 结论

**单 skill 更优**：我们的场景是"一条工作流"，不是"多个独立意图"。
多 skill 拓扑的收益（独立触发）用不上，代价（拼接成本、口径漂移）却实打实。
若未来长出**真正独立的意图**（如"对比两批 trace"、"从 trace 造评测任务"），再拆新 skill ——
届时本 skill 的 `scripts/` 与 `references/` 可直接复用为公共底座。
