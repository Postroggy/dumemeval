# [Challenge] 接入 MemoryArena Shopping 外部环境并完成 Agentic Memory E2E 评测

## 📌 1. 背景与目标

DuMemEval 需要支持真实的 agentic memory evaluation，而不是把外部环境任务摊平成一段文本。MemoryArena Shopping 包含商品数据、webshop 环境、逐步动作、环境反馈、任务状态和购买结果判定，适合作为一项跨层架构考核。

目标是：在不破坏现有扩展能力和评测语义的前提下，接入 MemoryArena Shopping，完成从官方代码研究、环境准备、Agent 执行、memory 使用、官方评分到 memory-on/off 对比的可复现闭环。

## 🔍 2. 官方参考资料

候选人必须自行阅读并锁定版本，以官方公开资料和实际源码为事实标准：

- Repository：<https://github.com/ZexueHe/MemoryArena>
- Dataset：<https://huggingface.co/datasets/ZexueHe/memoryarena>
- WebShop setup：<https://github.com/ZexueHe/MemoryArena/blob/main/setup_web_shopping.md>
- Official runner：<https://github.com/ZexueHe/MemoryArena/blob/main/run_shopping.py>
- Environment implementation：<https://github.com/ZexueHe/MemoryArena/tree/main/env/env_systems/web_shopping_env>
- Configurations：<https://github.com/ZexueHe/MemoryArena/tree/main/configs/web_shopping_configs>

提交中记录官方 commit/tag、调研日期、实际阅读的关键文件、许可证、数据版本和实现差异。以官方实际源码和可复现结果为准。

## 🎯 3. 任务范围

### 3.1 官方流程核验

核对并说明：

- 数据集配置、字段、split、任务组织和目标商品；
- shopping runner 如何加载配置、任务、agent、memory 和环境；
- 环境启动、初始化、动作、观察、reset、close 和 upstream 数据依赖；
- `search[query]`、`click[element]` 等动作的实际约束；
- memory 在官方流程中的写入、检索和跨回合使用方式；
- step/task 结果字段、购买匹配判定和聚合逻辑；
- 官方流程与 DuMemEval 映射后的已知偏差。

### 3.2 外部环境

实现可复现的环境生命周期：

```text
prepare → start → wait_until_ready → health_check → run → reset → cleanup
```

至少覆盖商品数据库和搜索索引准备、版本/配置/端口/数据路径记录、readiness 超时与诊断、task/session 隔离、异常退出清理和重复运行。服务启动、就绪和清理纳入评测流程。

### 3.3 Harbor 与 Agent runtime

必须使用真实 Harbor 执行 Agent，验证 runtime、模型、endpoint、环境变量、Skill/tool、缺失配置 fail-fast、fingerprint 和脱敏 trace。MCP 不是必做项；若实现 MCP，必须基于 Harbor 实际能力，不得以替代实现冒充该能力。

### 3.4 Agent 与 webshop 交互

至少完成一个真实、非平凡的 shopping 任务。Agent 必须通过官方环境动作完成必要的搜索、查看、选择和购买流程，不能绕过环境读取目标答案、直接调用 scorer，或以文本输出替代真实动作。证据必须能证明 Agent 消费 observation、环境状态发生变化且最终结果来自官方任务判定。

### 3.5 Memory 生命周期

至少验证两个具有关联的 session：前一 session 形成或更新任务相关记忆，后一 session 在相同任务语义下使用该记忆。必须区分外部环境状态与 Agent memory 状态，并验证 memory-on/off 隔离、task/session/environment scope、reset 语义、重试幂等和部分失败语义。

### 3.6 A/B 评测与报告

运行两组实验：

```text
A：memory disabled
B：memory enabled
```

除 memory 配置外固定 benchmark task、sample/session ID、agent、模型、prompt、temperature、Harbor runtime、环境版本/seed、judge、代码版本和数据版本；不可控差异必须记录。

报告必须区分 official benchmark score、verifier/judge observation、derived metrics、execution status、task/session/step evidence、A/B delta、失败原因和完整 provenance。

## 🚫 4. 明确不做什么

- 不要求接入全部 MemoryArena 场景；
- 不要求支持所有 Harbor runtime 或任意 MCP server；
- 不要求开发新的 agent、浏览器框架或 memory backend；
- 不要求重写全部 benchmark；
- 不要求构建 dashboard 或排行榜；
- 不要求创建没有真实消费者的通用抽象。

## 📦 5. 交付物

1. 官方实现调研和 parity/difference report；
2. 可从干净环境复现的最小数据与环境配置；
3. 环境启动、readiness、health、reset、cleanup 和失败证据；
4. Harbor 真实运行配置、版本信息和脱敏 trace；
5. memory-on/off 两次真实 LLM 运行；
6. 官方 scorer 对照 fixture；
7. JSON、Markdown 和 A/B comparison 结果；
8. 固定 fixture、失败路径、隔离/幂等和报告 schema 测试；
9. 设计文档、运行说明、故障排查和未完成项。

## 🧪 6. 验收标准

- [ ] 官方 commit/tag、入口、环境代码、评分逻辑和许可证已记录；
- [ ] 官方数据与环境依赖可以从干净环境准备；
- [ ] readiness、超时、reset、cleanup 和失败诊断可自动验证；
- [ ] 真实 Harbor Agent 完成至少一个官方 shopping 任务；
- [ ] trace 能证明 Agent 真实调用环境并消费 observation；
- [ ] 至少两个关联 session 验证 memory 生命周期；
- [ ] memory-on/off 的唯一变量和样本对齐成立；
- [ ] 官方 scorer 与 DuMemEval 结果有 fixture 级对照；
- [ ] official score、judge/verifier、derived metrics 和 execution status 未混为一个 score；
- [ ] 失败、超时、跳过、未测和 0 分语义可区分；
- [ ] 重试不会造成重复写入、重复购买或重复评分；
- [ ] JSON 适合 Agent 解析，Markdown 适合人阅读；
- [ ] 核心执行链没有退化为 benchmark/backend 特殊分支树；
- [ ] 不存在 mock、静态响应或 shim 冒充真实环境的情况。

## 📝 7. 提交说明

提交 Pull Request 时请附设计文档、精确命令、官方来源/版本/许可证、fixture 输入输出和评分对照、脱敏 artifact、已知差异、平台限制、未完成项，以及关键架构决策和替代方案。无法复现的环节必须标记 `verified`、`partial`、`unknown` 或 `blocked`，以可复现证据标明实际状态。
