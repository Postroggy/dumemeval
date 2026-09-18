# 数据集适配约定

- 状态：implemented
- 源码：`src/dumemeval/datasets/`
- 加数据集的 PR：在本目录新增 `<dataset>.md`，并在下表加一行。
- 各数据集官方步骤不一样（有没有 env、记忆怎么写入、按环境终态还是按文本打分）。对照和缺口见 [agentic-eval-pipelines.md](agentic-eval-pipelines.md)。不要把所有数据集都按 shopping 那套来接。

## 数据从哪来

三层，按需取用：

| 层 | 数据 | 获取 | 适用 |
|---|---|---|---|
| 零下载 | `data/smoke/`（官方子集，随仓库捆绑） | clone 即得 | `configs/smoke/` 真跑对照、CI |
| 一键下载 | 完整官方数据 → `~/.cache/dumemeval/datasets` | `dumemeval prepare` / `make prepare` | `configs/backends/` 全量实验 |
| 自备 | 任意本地目录 | 设 `DUMEMEVAL_DATA_DIR` | 已有数据集 / 离线环境 |

### 1. 先跑自带示例（零下载）

```bash
make example    # examples/locomo_mini.yaml + examples/data/locomo_mini.json
```

`examples/data/locomo_mini.json` 是**本项目自造**的 LoCoMo 格式迷你样例（1 对话 / 2 session / 4 题），只用于验证「装完能跑通」。**分数无学术意义**，不要引用。

### 2. 真跑 smoke（官方子集，随仓库捆绑，零下载）

```bash
make smoke-mock   # 编排验证（零 Docker / 零密钥）
make smoke        # Harbor 真跑（需 Docker + ANTHROPIC_*）
```

`data/smoke/` 下的 `locomo_smoke.json` / `shopping_smoke.jsonl` 是官方数据的
**精简子集**（格式不变，仅截断/取样），有记忆语义、能出官方口径，但**分数不可引用**。
来源与许可见 [data/smoke/README.md](../../data/smoke/README.md)。

### 3. 完整官方数据（一键下载）

```bash
dumemeval prepare                  # locomo + shopping 下载到缓存
dumemeval prepare --dataset locomo # 只要 locomo
```

缓存根默认 `~/.cache/dumemeval/datasets`（`DUMEMEVAL_DATA_DIR` 覆盖）。设计见 [prepare.md](prepare.md)。

### 4. 逻辑数据名（推荐：写名字，框架找文件）

内置数据统一用 `data.name` 引用，解析顺序 **仓库捆绑 `data/smoke/` → prepare 缓存**
（注册表在 `datasets/prepare.py` 的 `DATASET_REGISTRY`）：

| name | 捆绑（零下载） | 缓存（prepare 后） |
|---|---|---|
| `locomo_smoke` | data/smoke/locomo_smoke.json | 同构（prepare 重新生成） |
| `shopping_smoke` | data/smoke/shopping_smoke.jsonl | 同构 |
| `locomo` | — | locomo/locomo10.json |
| `bundled_shopping` | — | memoryarena/bundled_shopping.jsonl |

```yaml
task:
  benchmark: locomo
  data:
    type: local
    name: locomo_smoke   # 不要写路径；`doctor` 会列出可用 name
```

配置里从此**不再出现任何本机/缓存路径**——`configs/smoke/` 与 `configs/backends/`
均已改用 `name`。未命中时 loader 报错并列出可用 name + 下一步提示（`dumemeval prepare`
或设 `DUMEMEVAL_DATA_DIR` 或用显式 `path`）。

### 5. 自备数据 / 其他数据集

```yaml
task:
  benchmark: locomo
  data:
    type: local          # 也支持 hf / git（见 datasets/loader.py）
    path: /abs/or/relative/path/to/locomo10.json
```

其他 19 个 benchmark 的官方数据没有一键下载，从适配器 docstring 的 `Source:` 自取。
遵守各数据集的上游许可；本项目的 Apache-2.0 不覆盖第三方数据。目录说明见 [configs/README.md](../../configs/README.md)。

## 硬要求

1. **适配器 docstring 必须带可核对的来源 URL**：`Source:` 指向官方仓库 / HF dataset，`Paper:` 指向论文。**本地 `Dataset/` 路径不算来源**——社区拿不到你的本地盘。
2. **指标口径必须能核对**：calculator docstring 写清对应官方实现的文件名 + 关键函数。官方评测代码未公开时，明确写「自定义，非官方镜像」。
3. **禁止跨数据集套用指标**：A 的 F1 不能拿来算 B 的分数。

核对现有来源：

```bash
rg -n "^Source:|^Paper:" src/dumemeval --glob '*.py'
```

## 组织约定

- `BenchmarkAdapter.build_tasks` 产出 `list[EvalTask]`，一个样本 → 一个 task
- 问答 session 必须填 `SessionSpec.query`（与数据里的 question 原文一致），**不要**靠「取最后一个 observation」对齐
- session instruction 用数据集原文，不改写任务语义
- `evaluate()` 委托 `metrics/` 的 calculator，适配器不自己算分

## 已适配数据集

| 适配器 | 主要口径 | 口径来源 |
|---|---|---|
| `locomo` | token F1（normalize + Porter stem）+ 按类 accuracy | snap-research/locomo；accuracy 分桶同 OmniMemEval `locomo_metric.py` |
| `locomo_plus` | 6 类 LLM judge（correct 1.0 / partial 0.5 / wrong 0） | 官方 `prompt.py` |
| `longmemeval` | anscheck 模板 accuracy + abstention 分流 | 官方 `evaluate_qa.py` |
| `beam` | LLM judge 按 rubric 打分平均 | 官方 `compute_metrics.py` |
| `clbench` | solving rate（rubrics 全有或全无） | 官方 `eval.py` |
| `halumem` | 三阶段（integrity recall / interference accuracy / update 分类 / QA 分类） | 官方三阶段 prompt |
| `memoryarena_travel` | 派生在线 reward/slot 诊断；PS/SPS/SR 未覆盖 | 官方 `travel_env.py` 在线函数；自定义会话流程，见[五场景接入状态](memoryarena/README.md) |
| `memoryarena_shopping` | 环境购买 ASIN exact match + 完整 bundle overall_success；缺少环境证据为未测 | 官方 `match_ground_truth`；[接入状态和差异](memoryarena/README.md) |
| `memoryarena_search` | 最终综合问题的 GRADER_TEMPLATE 判分 → 按 query ID 平均 accuracy；截断为未测 | 官方 `run_search.py`、`search_agent/prompts.py` |
| `memoryarena_math` / `_phys` | yes/no 数学等价 judge → `is_correct` | 官方 `math_env.judge` |
| `memoryagentbench` | 按能力路由（substring / exact / Recall@5 / judge） | 官方 metadata.source 分流；ingest 按官方 `chunk_text_into_sentences` 切块（见 [memoryagentbench.md](memoryagentbench.md)） |
| `memorybench` | 28 子集按子集路由 | 各子集官方口径 |
| `personamem` | MCQ 选项字母匹配 accuracy | 官方 `inference.py` `extract_answer` |
| `scriptmem` | single / multi / ordering 精确字母匹配 | 官方 `score_mcq.py` |
| `memsim` | 选项字母 exact match + recall@step | 官方 `TimeFlow.py` |
| `memora` | FAMA = max(0, MPA − λ(1−FAA)) | 官方 `model_based_evaluator.py` |
| `memorycd` | MAE / RMSE / ROUGE-L / NDCG@5 / Recall@5 | 官方 `eval_core.py` |
| `streammembench` | fidelity / initial_evidence_use / feedback_incorporation / followup_reuse | 官方 `evaluation.metrics` |
| `evermembench_dynamic` | MC 规则判分 + OE LLM judge | 官方 `_parse_mc_answer` |
| `perltqa` | EM + token F1 | ⚠️ 官方评测代码未发布，适配层自定义 |

MemoryArena 的[接入设计](memoryarena/README.md)、[运行指南](memoryarena/clean-setup.md)和
[Issue #4 验收报告](memoryarena/acceptance.md)覆盖五场景、官方对照、真实 on/off、原始证据及已知限制。

## 未完成

- 多数数据集只有 smoke 级验证，缺少与官方脚本逐样本对比的 parity 报告
- `perltqa` 口径为自建，需等官方发布后校准
