# DuMemEval 社区任务包（草稿）

> 状态：draft · 生成方式：仓库审计 + 官方来源核验任务设计 · 不自动创建 GitHub Issue
>
> 本文把当前约 60 个零散想法收敛为 26 个可认领任务。benchmark 采用同类合并策略，通常一位贡献者负责约 3 个数据集；架构和跨模块契约任务建议由 maintainer/user 负责。

## 1. 使用说明

### 贡献前置规则

1. 先读 `GOVERNANCE.md`、`CONTRIBUTING.md`、`docs/README.md`。
2. 数据集必须以官方仓库、论文、评测代码和许可证为事实标准；本地缓存路径不是来源。
3. 每个数据集 PR 必须锁定官方 commit/tag，说明入口文件、评分函数和与 DuMemEval 的差异。
4. 固定 fixture parity 测试不得依赖真实 LLM；真实 LLM 只用于 integration/e2e。
5. 新扩展必须通过 registry；禁止在 `SessionRunner` 中增加 benchmark/backend 分支。
6. 指标未实现为 `null`/`n/a`，不能伪装为 0；mock 结果必须标注不可引用。

### 任务属性

- P0：阻塞可信评测主链；P1：核心能力；P2：重要扩展；P3：体验和长期治理。
- L0–L4：从文档/简单测试到跨模块架构。
- `owner: user/maintainer` 表示需要架构裁决，不是社区 good-first-issue。

## 2. 依赖拓扑

```text
来源/许可证/version manifest (#01)
        ↓
结果与 artifact 契约 (#02–#05)
        ↓
protocol/environment/adapter contract (#06–#09)
        ↓
benchmark parity / benchmark 准入 (#10–#17)
        ↓
protocol lifecycle (#18)
        ↓
Harbor/runtime 能力 (#19–#21)
        ↓
judge/metrics/report/compare (#22–#25)
        ↓
CI、文档和社区治理 (#26)
```

无真实依赖的任务可并行。每个任务的“依赖”只表示必须先存在的契约或工具。

## 3. 任务索引

| ID | 标题 | 类型 | 优先级 | 难度 | 建议负责人 |
|---|---|---|---|---|---|
| #01 | 建立 benchmark parity matrix 与来源清单 | research | P0 | L2 | community |
| #02 | 收口 TaskExecution、TaskResult、Report 结果模型 | architecture | P0 | L4 | user/maintainer |
| #03 | 统一 benchmark scorer、verifier、metrics 的结果优先级 | architecture | P0 | L4 | user/maintainer |
| #04 | 统一评测状态、失败、跳过和未测语义 | architecture | P0 | L4 | user/maintainer |
| #05 | 稳定 run/task/session/artifact schema 与恢复语义 | architecture | P1 | L4 | user/maintainer |
| #06 | 重画 protocol、pipeline、environment 边界 | architecture | P1 | L4 | user/maintainer |
| #07 | 建立 adapter contract test kit | testing/adapter | P0 | L2 | community |
| #08 | 完善 namespace、snapshot、reset 和并发隔离 | adapter | P1 | L3 | community |
| #09 | 修复数据集 prepare/loader/config 边界 | refactor | P1 | L3 | community |
| #10 | LoCoMo / LoCoMo+ / LongMemEval 官方 parity | benchmark | P0 | L3 | community |
| #11 | MemoryAgentBench / MemoryBench / MemoryCD 官方 parity | benchmark | P1 | L3 | community |
| #12 | MemoryArena 环境型 benchmark 官方 parity | benchmark/environment | P1 | L3 | community |
| #13 | MemoryArena Shopping / MemSim / Memora parity | benchmark | P1 | L3 | community |
| #14 | HaluMem / StreamMemBench / EverMemBench-Dynamic parity | benchmark | P1 | L4 | community |
| #15 | BEAM / CL-bench / PersonaMem parity | benchmark | P2 | L3 | community |
| #16 | PerLTQA / ScriptMem / 对话型 benchmark parity | benchmark | P2 | L3 | community |
| #17 | 建立新 benchmark 资格审查和接入模板 | research/docs | P2 | L2 | community |
| #18 | 实现 memory_train_backup_test 的 backup/restore | protocol | P1 | L3 | community |
| #19 | Harbor runtime capability matrix 与 fail-fast preflight | harbor | P1 | L3 | community |
| #20 | Harbor Skill 版本、路径和可复现性指纹 | harbor | P1 | L2 | community |
| #21 | Harbor MCP 与 tool/skill trace PoC | harbor | P2 | L4 | community |
| #22 | Judge 配置、缓存、重放和失败治理 | judge | P1 | L3 | community |
| #23 | Quality/Utility/Efficiency/Trace 指标语义收口 | metrics | P0 | L4 | user/maintainer |
| #24 | 人读 Markdown 与 agent 读 JSON 报告 | reporting | P1 | L3 | community |
| #25 | 严格 A/B compare、fingerprint、对齐和统计解释 | comparison | P1 | L3 | community |
| #26 | CI、smoke、贡献者文档和遗留入口治理 | engineering/docs | P2 | L2 | community |

---

## 4. Issue 草稿

以下标题和结构可直接复制到 GitHub Issue。官方来源字段要求贡献者按实际研究结果填写；当前未确认的内容不得凭印象补齐。

### #01 建立 benchmark parity matrix 与来源清单

- **类型/属性**：Research · P0 · L2 · `owner: community` · `research benchmark docs`
- **背景**：当前已有 21 个注册 benchmark，但来源、版本、官方入口、评分口径和实现状态缺少一张可审计的总表。
- **范围**：盘点每个 benchmark 的官方 repo/数据页、论文、许可证、commit/tag、入口脚本、字段/切分、task/session 时序、评分函数、当前 adapter 映射和差异。
- **不做**：不在本 Issue 内实现所有 adapter；不以本地 `Dataset/` 路径代替官方来源。
- **验收**：
  - [ ] 新增 parity matrix，覆盖当前 21 个 benchmark。
  - [ ] 每行包含来源 URL、版本、许可证、官方评分入口和 DuMemEval 状态。
  - [ ] 未核验字段显式写为 unknown，并记录原因。
  - [ ] 至少为后续 #10–#16 建立可引用的官方事实索引。
- **证据**：来源 URL、commit/tag、引用文件路径、研究记录；无真实 LLM 要求。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：无。

### #02 收口 TaskExecution、TaskResult、Report 结果模型

- **类型/属性**：Architecture · P0 · L4 · `owner: user/maintainer` · `architecture models`
- **背景**：生产链路仍有新旧结果模型并存，调用者难以判断哪个是权威输出。
- **范围**：定义一次 execution、一个 task、一次 run、最终 report 的边界；移除或隔离 legacy `EvalResult`；明确序列化兼容策略。
- **不做**：不借机重写全部 benchmark scorer。
- **验收**：
  - [ ] 设计文档给出对象生命周期和依赖方向。
  - [ ] 生产路径只有一个权威结果模型。
  - [ ] JSON schema 有固定 fixture 测试和版本字段。
  - [ ] 旧字段的迁移/读取策略明确且不静默丢数据。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#01；建议先于 #03–#05。

### #03 统一 benchmark scorer、verifier、metrics 的结果优先级

- **类型/属性**：Architecture · P0 · L4 · `owner: user/maintainer` · `architecture metrics verifier`
- **背景**：benchmark score、verifier score、metrics score 同时存在，没有唯一权威性。
- **范围**：规定 benchmark official score 是任务效用的权威结果；verifier 是判定证据/可选派生层；metrics 是横向分析层；统一命名、来源和展示优先级。
- **不做**：不把所有官方分数替换成 LLM judge；不删除可追溯的辅助分数。
- **验收**：
  - [ ] 报告 schema 能区分 `official_score`、`verdict`、`derived_metrics`。
  - [ ] 每个分数有 producer、scope、aggregation、status。
  - [ ] Markdown 明确展示权威结果，JSON 明确机器消费路径。
  - [ ] 同一 fixture 验证优先级和缺失值语义。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#02。

### #04 统一评测状态、失败、跳过和未测语义

- **类型/属性**：Architecture · P0 · L4 · `owner: user/maintainer` · `architecture reliability`
- **范围**：定义 success/failed/skipped/timeout/partial/not-measured；区分测得 0、未执行、执行失败和评分失败；明确 run 是否可发布。
- **不做**：不通过默认 0 分掩盖错误；不强制所有失败自动重跑。
- **验收**：状态枚举、转移图、JSON 示例、report 展示、失败 fixture 和单元测试齐全；下游 compare 不再把缺失当 0。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#02。

### #05 稳定 run/task/session/artifact schema 与恢复语义

- **类型/属性**：Architecture · P1 · L4 · `owner: user/maintainer` · `architecture artifacts`
- **范围**：定义 run manifest、task/session artifact、checkpoint、输入指纹、代码/配置/模型/数据版本和恢复点。
- **不做**：不实现分布式数据库或云存储。
- **验收**：冷启动、session 中断、恢复、重复执行四个 fixture 均能验证幂等性；artifact 可定位到 task/session；schema 有版本和迁移说明。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#02、#04。

### #06 重画 protocol、pipeline、environment 边界

- **类型/属性**：Architecture · P1 · L4 · `owner: user/maintainer` · `architecture protocol environment`
- **范围**：明确 protocol 只编排 memory 生命周期，pipeline 负责 run 级流程，environment 只准备 agent 交互环境，benchmark 负责官方评分。
- **不做**：不新增第二套编排框架。
- **验收**：依赖拓扑和调用时序文档更新；`SessionRunner` 无 benchmark/backend 分支；环境 provider 不计算 benchmark 分数；至少有一个静态依赖检查。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#02–#05。

### #07 建立 adapter contract test kit

- **类型/属性**：Testing · P0 · L2 · `owner: community` · `adapter testing`
- **范围**：为 setup、seed_history、inject、snapshot、observe、teardown 和错误清理提供统一 contract fixture，覆盖 none、directory、HTTP 类 adapter。
- **不做**：不测试具体产品的官方评分。
- **验收**：新 adapter 可通过一条命令运行 contract tests；失败清理、重复 setup、空 memory、超时和隔离均有测试；文档给出最小实现步骤。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#06。

### #08 完善 namespace、snapshot、reset 和并发隔离

- **类型/属性**：Adapter · P1 · L3 · `owner: community` · `adapter reliability`
- **范围**：补齐 memory scope、任务/实验隔离、snapshot/reset 语义、并发安全和 readiness；以现有 adapters 为样本。
- **不做**：不新增 memory 产品。
- **验收**：两个并发 task 互不可见；reset 后无残留；snapshot 可恢复；错误路径 teardown；固定 integration fixture 和文档齐全。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#07。

### #09 修复数据集 prepare/loader/config 边界

- **类型/属性**：Refactor · P1 · L3 · `owner: community` · `datasets config`
- **范围**：移除 `prepare.py` 中特定数据集硬编码；以 registry/声明式 source 支持 local、HF、git 或官方脚本；统一 `configs/`、`examples/`、`src/dumemeval/config/` 的职责。
- **不做**：不承诺任意网站自动下载；不改变官方许可证。
- **验收**：新增一个非 LoCoMo 数据集无需修改核心分支；source、版本、缓存、校验失败有清晰错误；CLI help、fixture 和文档同步。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#01、#06。

### #10 LoCoMo / LoCoMo+ / LongMemEval 官方 parity

- **类型/属性**：Benchmark · P0 · L3 · `owner: community` · `benchmark dataset parity`
- **范围**：按官方代码核验字段、切分、session 编排、memory 使用方式和评分，补齐 adapter 与固定 fixture parity 测试。
- **不做**：不把三者强行合并成一个官方评分；不修改官方数据。
- **验收**：三者各有来源 commit/tag、入口函数、评分对照、固定 fixture；结果与官方代码在可比较输入上逐项一致；差异列表写入文档。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#01、#06、#09。

### #11 MemoryAgentBench / MemoryBench / MemoryCD 官方 parity

- **类型/属性**：Benchmark · P1 · L3 · `owner: community` · `benchmark dataset parity`
- **范围**：同 #10，重点核验长程记忆、多轮输入、任务边界和官方聚合。
- **验收**：每个 benchmark 至少有固定 fixture；fixture 同时经过官方 scorer 和 DuMemEval scorer；输出关键字段与分数差异；差异原因和未完成项可追溯。
- **测试与证据**：提交官方 repo、commit/tag、入口文件、评分对照表和测试命令；无法执行官方 scorer 时标记 unknown/blocked。
- **不做**：不重定义官方指标。
- **依赖**：#01、#02、#03、#09。

### #12 MemoryArena 环境型 benchmark 官方 parity

- **类型/属性**：Benchmark/Environment · P1 · L3 · `owner: community` · `benchmark environment`
- **范围**：Math、Search、Travel、Phys；核验官方环境启动、agent 交互、reset、评分与 memory 生命周期。
- **不做**：不把 environment provider 变成 scorer；不同时实现所有 Harbor runtime。
- **验收**：每个环境有 health check、usage hint、env vars、cleanup、固定 smoke；官方评分入口与 DuMemEval 结果可追溯。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#06、#19。

### #13 MemoryArena Shopping / MemSim / Memora parity

- **类型/属性**：Benchmark · P1 · L3 · `owner: community` · `benchmark dataset parity`
- **验收**：三者分别核验官方字段、切分、task/session 编排、memory 时序、环境依赖和 scorer；按实际 pipeline 补 adapter、固定 fixture 和差异文档。
- **验收**：三者各有来源与版本记录；各有固定 fixture，并输出官方 scorer 与 DuMemEval scorer 对照；环境依赖若存在必须单独说明。
- **测试与证据**：提交来源 URL、commit/tag、关键入口、fixture 输入输出和分数对照；官方 scorer 无法运行时标记 unknown/blocked。
- **不做**：不将购物任务的外部环境分数塞进 adapter。
- **依赖**：#01、#06。

### #14 HaluMem / StreamMemBench / EverMemBench-Dynamic parity

- **类型/属性**：Benchmark · P1 · L4 · `owner: community` · `benchmark feedback dynamic`
- **范围**：重点补齐 feedback、revise、write-back、动态数据和官方错误/幻觉判定流程。
- **验收**：官方代码关键函数有引用；fixture 覆盖至少一次 revise/write-back；评分与官方实现逐项对照；失败状态不转成 0。
- **不做**：不凭空发明通用 feedback hook。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#01、#03、#06、#18。

### #15 BEAM / CL-bench / PersonaMem parity

- **类型/属性**：Benchmark · P2 · L3 · `owner: community` · `benchmark dataset parity`
- **验收**：三者各有来源、许可证、切分、官方入口、评分、DuMemEval 映射和固定 fixture；fixture 输出官方/本地评分对照；不能确认的官方事实列入 unknown。
- **测试与证据**：提交来源 URL、版本、引用文件、fixture 结果和差异清单。
- **不做**：不修改论文口径。
- **依赖**：#01、#09。

### #16 PerLTQA / ScriptMem / 对话型 benchmark parity

- **类型/属性**：Benchmark · P2 · L3 · `owner: community` · `benchmark dataset parity`
- **范围**：接入 PerLTQA、ScriptMem，候选第三个 benchmark 不属于本 Issue 的实现范围，统一由 #17 进行资格审查。
- **验收**：至少两个已有 benchmark 完成可运行 parity；候选第三者有官方来源和准入结论；文档说明为何属于同一 pipeline 类型。
- **不做**：不为了凑数量接入未经核验的数据集。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#01、#17。

### #17 建立新 benchmark 资格审查和接入模板

- **类型/属性**：Research/Docs · P2 · L2 · `owner: community` · `research benchmark`
- **范围**：定义官方来源、许可证、可复现评分、memory 生命周期相关性、环境可获得性、数据安全和维护成本的准入清单。
- **验收**：模板可用于一个新 benchmark；给出 pass/fail/unknown 示例；贡献指南明确先研究后实现。
- **不做**：不承诺自动接入所有新论文。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#01。

### #18 实现 memory_train_backup_test 的 backup/restore

- **类型/属性**：Protocol · P1 · L3 · `owner: community` · `protocol lifecycle`
- **范围**：实现 backup、restore、test session 的真实生命周期，定义失败恢复、版本不兼容和隔离。
- **不做**：不把 snapshot 当作所有后端天然支持的能力。
- **验收**：协议注册后可运行；backup 后清空再 restore 可恢复固定 fixture；restore 失败可观测；无能力 adapter 明确 fail-fast；文档更新。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#05、#07、#08。

### #19 Harbor runtime capability matrix 与 fail-fast preflight

- **类型/属性**：Harbor · P1 · L3 · `owner: community` · `harbor runtime`
- **范围**：定义 runtime capability/preflight contract，调查当前 Harbor 能配置的 runtime、skill、MCP、网络、secret、环境变量和资源能力；执行前检查配置完备性。
- **不做**：不实现 Harbor 的替代品。
- **验收**：能力矩阵注明 Harbor 版本/commit；缺少必需能力时在运行前失败并列出修复项；基础配置 fingerprint 写入 artifact；文档给出真实 smoke 证据。
- **测试与证据**：提交能力矩阵、preflight 成功/失败日志、版本信息和 artifact 样例；不得依赖 #20 的 Skill 专用实现。
- **依赖**：#05、#20。

### #20 Harbor Skill 版本、路径和可复现性指纹

- **类型/属性**：Harbor · P1 · L2 · `owner: community` · `harbor skill docs`
- **范围**：复用 Harbor 原生 Skill 注入；记录 skill 来源、路径、版本/哈希和启用状态；修正文档与示例。
- **不做**：不创建新的 skill marketplace 或通用 tool 抽象。
- **验收**：示例可在干净环境构建；作为 capability provider 接入 #19；运行前检查 skill 可用；报告记录 skill 来源/路径/版本指纹；缺少 skill 不会跑到最后才失败。
- **测试与证据**：提交 Harbor 版本、skill 来源和哈希、干净环境命令输出及失败 preflight 日志。
- **依赖**：#19。

### #21 Harbor MCP 与 tool/skill trace PoC

- **类型/属性**：Harbor · P2 · L4 · `owner: community` · `harbor mcp trace`
- **范围**：先用最小 MCP/Skill 场景验证 Harbor 原生配置、注入和 trace；形成能力限制报告。
- **不做**：不承诺一次性支持任意 MCP server。
- **验收**：PoC 在声明版本上可运行；tool/skill/MCP 调用有结构化 trace；失败和 secret 脱敏；若 Harbor 不支持某能力，提供明确替代边界而非 shim。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#19、#20。

### #22 Judge 配置、缓存、重放和失败治理

- **类型/属性**：Judge · P1 · L3 · `owner: community` · `judge reliability`
- **范围**：统一 judge endpoint/model/temperature/timeout/retry/preflight；实现可选缓存和 replay；区分 judge failure 与被评样本低分。
- **不做**：不把 judge 分数替代 benchmark official score。
- **验收**：缺少 key/endpoint 在运行前发现；相同输入可 replay；timeout/invalid response 有状态和证据；缓存键包含 prompt/model/config 版本；测试不依赖真实 LLM。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#03、#04、#05。

### #23 Quality/Utility/Efficiency/Trace 指标语义收口

- **类型/属性**：Architecture/Metrics · P0 · L4 · `owner: user/maintainer` · `architecture metrics`
- **范围**：确定四类指标的输入、输出、scope、聚合和缺失语义；明确哪些属于官方 benchmark，哪些属于横向分析。
- **不做**：不为每个新指标创建独立框架。
- **验收**：MetricInput 与 report schema 对齐；每个现有 calculator 有来源、公式、边界和 fixture；缺失值为 null；官方分数不会被横向指标覆盖。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#02–#04。

### #24 人读 Markdown 与 agent 读 JSON 报告

- **类型/属性**：Reporting · P1 · L3 · `owner: community` · `reporting docs`
- **范围**：生成同一 run 的人类摘要和机器报告；包含配置、来源、样本、状态、权威分数、辅助指标、失败和 provenance。
- **不做**：不做交互式 dashboard。
- **验收**：固定 fixture 生成 Markdown 和 JSON；两者关键数值一致；JSON 有 schema/版本；Markdown 能直接回答 memory-on vs memory-off 的差异和限制。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#02–#05、#23。

### #25 严格 A/B compare、fingerprint、对齐和统计解释

- **类型/属性**：Comparison · P1 · L3 · `owner: community` · `comparison statistics`
- **范围**：定义 memory-on/off 控制变量、配置 fingerprint、样本 ID 对齐、配对差值、分类统计和置信区间。
- **不做**：不把不同数据切分或不同 agent 配置直接排名。
- **验收**：不变量不一致时 compare fail-fast；相同样本可输出 task/category/session 级 delta；缺失样本不当 0；报告注明统计方法、样本量和不可解释边界。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#03–#05、#24。

### #26 CI、smoke、贡献者文档和遗留入口治理

- **类型/属性**：Engineering/Docs · P2 · L2 · `owner: community` · `ci docs cleanup`
- **范围**：清理 `doctor.py` 相关遗留测试/入口；核对 docs、README、quick-start、configs、examples、smoke 数据；建立 mock/integration/real smoke/e2e 分层与贡献者检查。
- **不做**：不把 real LLM smoke 放进每次快速单测；不删除仍被使用的文档示例而不迁移。
- **验收**：失效测试和入口清零；至少一条 mock、一条固定 fixture integration、一条 Harbor real smoke 路径有明确 CI/手册边界；文档中的注册数量、目录和命令与实际一致；贡献者能按文档完成最小验证。
- **测试与证据**：提交本任务对应的设计/研究记录、固定 fixture（如适用）、精确命令输出和变更前后证据；未能核验的行为必须标记 unknown。
- **依赖**：#07、#09、#19、#24。

## 5. 贡献者提交证据清单

每个 PR 至少附：

- 变更文件和设计文档链接；
- 使用的官方来源 URL、commit/tag、论文和许可证；
- 固定 fixture 及其预期输出；
- 运行过的精确命令和结果；
- 对官方实现的逐项差异说明；
- 未完成、平台限制或 runtime-only 风险；
- 明确说明是否运行真实 LLM/Harbor，不能把 mock 结果称为实验结果。

## 6. 维护者分发建议

- 先由 maintainer 完成 #01–#06 的架构基线，再开放 #07–#22、#24–#26。
- 数据集任务每组只分配一位主负责人，reviewer 可按 benchmark 子项拆分核验。
- #02、#03、#04、#05、#06、#23 属于架构决策，不建议社区直接改核心契约。
- `good first issue`：#01、#07、#17、#20、#26 的文档/清单子项。
- `research`：#01、#10–#17、#19、#21。
- `help wanted`：#07–#18、#20–#22、#24–#26。
