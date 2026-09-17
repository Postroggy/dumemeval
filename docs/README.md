# 设计文档

**任何 PR 都必须有设计文档，无例外。** 顺序：写文档 → 实现 → 测试 → 提 PR 前回头更新文档（把「计划」改成「实际」）→ 提 PR。

新功能、重构、修 bug、改配置、动 CI、改文档结构，都算。**改动越小，文档越短——不是免写。**

一个功能一篇文档，放进它所属模块的目录。**不要**建流水号目录、不要建「决策记录」这类只增不减的档案——文档跟着代码走，代码改了就改文档，代码删了就删文档。

## 目录 = 源码模块

| 目录 | 对应源码 | 放什么 |
|---|---|---|
| `architecture/` | 跨模块 | 分层与依赖禁区、评测循环、扩展点契约、**开发规范**（dev-standards.md）、**CI 口径**（ci.md） |
| `adapters/` | `src/dumemeval/adapters/` | 每个 memory 后端一篇：生命周期怎么映射到该产品 |
| `datasets/` | `src/dumemeval/datasets/` | 每个数据集一篇：来源 URL、如何变成 EvalTask |
| `metrics/` | `src/dumemeval/metrics/` | 每个指标族一篇：口径、官方实现出处、语义边界 |
| `lifecycle/` | `src/dumemeval/lifecycle/` | 协议、跨 session 传递、并行与续跑 |
| `execution/` | `src/dumemeval/execution/` | 执行引擎接入（Harbor、mock、未来引擎）；**默认 real smoke 矩阵**（`smoke-matrix.md`） |
| `verifier/` | `src/dumemeval/verifier/` | 判分器与 judge 工程（重试、多数票） |
| `reporting/` | `pipeline/` / `artifacts/` / `comparison/` | 报告、溯源、跨 run 比较 |

找不到归属，说明这个功能跨了模块——先想清楚它该落在哪一层，而不是新开目录。

## 文件命名

`<功能>.md`，小写连字符。例：`adapters/hermes-builtin.md`、`metrics/trace.md`、`reporting/compare.md`。

## 不同改动写什么

| 改动类型 | 文档去哪 | 篇幅 |
|---|---|---|
| 新功能 / 新扩展点实现 | `docs/<模块>/<功能>.md` 新增一篇 | 完整（含备选方案与否决理由） |
| 修 bug | 更新受影响功能那篇的「语义边界」或「未完成」；无对应文档则新建 | 几行：什么前提下会错、为什么之前没发现 |
| 重构（行为不变） | 更新对应模块文档的「方案」段 | 短：为什么改结构、为什么不改行为 |
| 配置 / CI / 工程 | `docs/architecture/` 对应篇 | 短 |
| 只改文档 | 就在被改的那篇里说明缘由 | 一句话 |

## 一篇文档写什么

按需取用，不必凑齐。新功能与重构**必填「备选方案与否决理由」**——没有它就不是设计文档，只是实现说明。

```markdown
# <功能名>

- 状态：draft / implemented
- 源码：src/dumemeval/xxx/yyy.py
- 关联：Issue #xx · PR #xx

## 问题
要解决什么，现状为什么不够。

## 方案
怎么做，用哪个扩展点，为什么不用改 SessionRunner。

## 备选方案与否决理由
| 方案 | 否决理由 |

## 语义边界
这个功能测不出什么，哪些数字不能过度解读。

## 未完成
明确列出留给后续的部分。
```

## 硬要求

- **写差异，不写教程**：只写「为什么这样而不是那样」，how 交给代码
- **数据集文档必须有可核对的来源 URL**（官方仓库 / HF），本地 `Dataset/` 路径不算
- **实现后回改**：文档与代码不一致时，文档是错的那个
- **标明未完成**：不要让读者以为功能已经全做完
