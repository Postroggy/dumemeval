# MemoryArena 外部环境接入考核评分标准

- 对应任务：`docs/community/challenge-memoryarena-environment.md`
- 总分：100 分
- 通过建议线：70 分
- 强制门禁：下列一票否决项不能满足时，即使总分达到 70 分也不通过。

## 一票否决项

1. 没有真实启动并使用外部环境，只用 mock、静态响应或直接读取答案。
2. 没有真实 Harbor 运行证据，或用本地脚本冒充 Harbor。
3. memory-on 与 memory-off 共享未清理的 memory/environment 状态，导致 A/B 无效。
4. 未核对官方代码和 scorer，却声称完成官方 parity。
5. 环境启动、配置或 Judge 失败被静默转换成任务 0 分。
6. secret/API key 出现在日志、trace 或提交文件中。
7. 通过在通用 runner 中堆积 benchmark/backend 特殊分支完成任务，且没有合理的架构解释。
8. 不能提供从环境构建到最终报告的真实运行证据。

## 评分总表

| 维度 | 分值 |
|---|---:|
| 官方事实与评分 parity | 20 |
| 外部环境工程 | 20 |
| Harbor / Agent runtime 集成 | 15 |
| Memory 生命周期与实验有效性 | 15 |
| 架构设计与取舍 | 15 |
| 测试、可靠性与可诊断性 | 10 |
| 文档与结果表达 | 5 |
| **总计** | **100** |

## 1. 官方事实与评分 parity：20 分

### 18–20 分

- 明确锁定官方仓库和 commit/tag；
- 定位实际入口、环境协议、任务数据和 scorer；
- 能解释官方 `web_shopping` / `bundled_shopping` 数据关系；
- 固定 fixture 同时经过官方路径和 DuMemEval 路径；
- 对每个差异给出证据和原因；
- 未核验内容明确标记 unknown/partial/blocked。

### 12–17 分

- 大体接入官方流程，但部分关键函数或聚合口径只引用文档；
- 有 fixture，但对照不完整或差异分析较弱。

### 0–11 分

- 只新增数据解析，没有证明官方流程一致；
- 评分结果无法追溯；
- 把本地结果直接称为官方分数。

## 2. 外部环境工程：20 分

### 18–20 分

- 环境源码/镜像/数据版本可追溯；
- prepare、start、readiness、health、reset、cleanup 边界清晰；
- 使用超时、状态和诊断信息，而不是固定等待；
- task/session 隔离可证明；
- 重复运行、异常退出和启动失败均有验证。

### 12–17 分

- 环境能稳定运行，但部分生命周期仍依赖手工步骤；
- cleanup 或失败恢复覆盖不足。

### 0–11 分

- 只能手工启动服务；
- 依赖机器上已有进程或残留数据；
- 环境错误被吞掉或表现成低分。

## 3. Harbor / Agent runtime 集成：15 分

### 14–15 分

- Harbor 真实运行；
- runtime、Skill/tool、endpoint、环境变量和版本都有 provenance；
- 缺少配置在运行前 fail-fast；
- agent 交互 trace 可读且 secret 已脱敏；
- 没有自行复制一套 Harbor 执行框架。

### 9–13 分

- Harbor 运行成功，但能力检查、版本指纹或 trace 不完整。

### 0–8 分

- Harbor 只存在于文档，没有真实证据；
- 配置硬编码或失败到最后才发现；
- 用 shim/占位层遮盖能力缺口。

## 4. Memory 生命周期与实验有效性：15 分

### 14–15 分

- 至少两个关联 session；
- 能证明 memory 的写入、检索、注入和后续使用；
- 环境状态、memory 状态、task scope、session scope 分离；
- 重试幂等，不重复写 memory 或购买；
- memory-on/off 的唯一变量和数据对齐可信。

### 9–13 分

- 跨 session 可用，但隔离、重试或 provenance 仍有边界缺口。

### 0–8 分

- 只是单 session memory 注入；
- 用环境残留伪装记忆效果；
- A/B 控制变量不成立。

## 5. 架构设计与取舍：15 分

### 14–15 分

- 能从官方流程识别通用生命周期与 benchmark-specific 语义；
- 没有把 shopping 逻辑塞进通用 runner；
- 结果模型能区分 official score、verifier/judge、derived metrics、execution status；
- 新增抽象都有真实消费者；
- 设计文档解释了职责边界、依赖方向、失败语义和未选择的方案。

### 9–13 分

- 设计可用，但有局部重复或边界不够简洁。

### 0–8 分

- 复制专用 pipeline；
- 大量 `if benchmark/backend`；
- 把 environment、memory、scorer、runtime 混成一个对象；
- 过度抽象，接口多于实际需求。

## 6. 测试、可靠性与可诊断性：10 分

### 9–10 分

至少覆盖：

- 官方 scorer fixture parity；
- 环境协议正常路径；
- readiness/start 失败；
- reset/cleanup；
- memory 隔离；
- 重试幂等；
- A/B 样本对齐；
- 报告 schema。

测试验证状态和最终产物，而不只是 mock 方法调用。

### 5–8 分

正常路径测试充分，但失败、隔离或幂等覆盖不完整。

### 0–4 分

只有 happy-path 或 import 测试；真实失败无法诊断。

## 7. 文档与结果表达：5 分

- 2 分：干净环境运行说明和精确命令；
- 1 分：官方来源、版本、许可证和差异记录；
- 1 分：Markdown 对人清晰，JSON 对 Agent 稳定；
- 1 分：明确 limitations、unknown、partial 和未完成项。

## 代码质量扣分项

在上述维度中额外执行以下扣分，最低扣至 0 分：

| 问题 | 建议扣分 |
|---|---:|
| 静默捕获异常或把失败变 0 分 | -3～-8 |
| 硬编码 endpoint、路径、secret 或版本 | -2～-6 |
| 无资源清理或进程泄漏 | -2～-6 |
| 重试造成重复写入/购买/评分 | -3～-8 |
| 无类型约束、无状态校验且已造成边界 bug | -1～-4 |
| 复制已有 helper 或引入无消费者抽象 | -1～-4 |
| 文档与实际命令不一致 | -1～-4 |
| 修改范围大但没有迁移/兼容说明 | -1～-5 |

## 评审流程

1. 先运行候选人提供的最小 fixture 和自动化测试。
2. 再在干净环境启动外部服务，验证 prepare/readiness/reset/cleanup。
3. 核对 Harbor 真实运行记录和 trace。
4. 抽查一个任务的官方 scorer 对照。
5. 分别检查 memory-on、memory-off 和 comparison artifact。
6. 最后阅读设计文档，对照实际代码判断抽象是否必要、边界是否成立。

评审不能只根据最终分数判断实现质量。一个任务得到较低官方分数并不必然代表代码错误；应先区分：

```text
agent 任务能力差
环境/配置失败
官方 parity 偏差
memory 生命周期错误
judge/metrics 失败
```

## 评审结论模板

```text
总分：__/100
结论：通过 / 需要修改 / 不通过

官方 parity：
环境工程：
Harbor/runtime：
Memory 生命周期：
架构设计：
测试可靠性：
文档结果：

阻塞问题：
必须修改：
建议改进：
加分项：
未验证项：
```
