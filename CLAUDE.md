# DuMemEval 项目规范

社区贡献的权威入口是仓库根目录 **GOVERNANCE.md**（目标 / 分层禁区 / 扩展点）和 **CONTRIBUTING.md**；工程硬规范的权威来源是 **docs/architecture/dev-standards.md**。本文件是给 AI agent 的速查，与 dev-standards 同源。

## 强制规范

### 1. 所有数据模型必须使用 pydantic
- **禁止**使用 `dataclass` / `TypedDict` / `NamedTuple` 定义数据模型
- 所有核心概念（EvalTask / SessionSpec / MemorySpec / 结果模型 / Verdict / SessionOutcome）必须是 `pydantic.BaseModel`
- 使用 `Field(...)` 做约束（默认值、描述、校验），使用 `field_validator` / `model_validator` 做跨字段校验
- 配置加载必须经 pydantic 模型校验（禁止裸 dict 传递）

### 2. 类型注解
- 所有函数签名必须有完整类型注解（参数 + 返回值）
- 禁止 `Any` 滥用——能用 `Literal` / `Enum` / 具体模型就不用 `Any`
- 新代码必须过 `mypy --strict`

### 3. 代码质量
- 必须过 `ruff check`（严格模式）+ `ruff format`
- 必须写测试（`pytest`，`--strict-markers`）：新增模块必须有对应测试文件
- 禁止 `except Exception: pass` 吞异常（可回退的场景需区分"兼容性回退"与"真错误"，真错误必须抛出）
- 模块职责单一：超过 300 行是拆分信号
- 完成一个阶段后，派 subagent 强校验（职责/依赖/naive 实现/测试覆盖）

### 4. 工程
- 依赖由 `uv` 管理（pyproject.toml + uv.lock），禁止手动 pip install
- src 布局：`src/dumemeval/`
- 模块划分遵循核心哲学（单向依赖：core ← 其余 ← cli）：
  - `core/`：核心概念（config 配置模型 / protocol 评测协议 / retry 瞬时重试）
  - `cli/`：子命令（`run` / `doctor` / `list` / `compare` / `prepare`）；`__init__.py` 只做 parser 组装
  - `models/`：领域模型（EvalTask/SessionSpec/MemorySpec/SessionOutcome/结果/VerifierSpec/MemoryFact；`run.py` 放 run 级：RunSummary/RunProvenance/RunComparison）
  - `adapters/`：memory 后端接入（base/directory/http/hermes_builtin/everos/none/hermes_format/registry）
  - `lifecycle/`：memory 生命周期（runner 编排 / parallel 跨 task / checkpoint 续跑 / memory_transfer 传递 / hooks 事件）
  - `execution/`：隔离执行（executor 协议 / mock / harbor_bridge / trial_config / task_dir）
  - `verifier/`：判分体系（base 抽象 / llm 主判分器 / clients 双 provider / retry 多数票 / parsers / prompts / rule+factory）
    - 瞬时重试在 `core/retry.py`（adapters 可共用，禁止 adapters → verifier）
    - **主路径：LLM as judge**（语义判分）；rule 仅用于测试/结构化场景
  - `datasets/`：数据管理（`loader.py` 从哪读：local/hf/git + 版本锁定；`benchmark.py` + `benchmarks/` 怎么变成 EvalTask）
    - **BenchmarkAdapter**：负责 `build_tasks()`；`evaluate()` 委托 `metrics/` 计算器
    - 适配器 docstring 必须带 `Source:` 数据集官方来源 URL
  - `environments.py`：任务环境扩展点（`TaskEnvironmentProvider` + `register_task_environment`；内置 `http` / `webshop`，shopping 任务接 webshop，travel/search/math 不接）
  - `metrics/`：★ 统一指标计算层（MetricCalculator + MetricsAggregator + **registry**）
    - 横切四维 quality / utility / efficiency / trace + 各数据集官方口径
    - 一次评测 → 聚合 `result.metrics` + 类型化 quality/utility/efficiency/trace/benchmark
    - 加数据集：`register_calculator(Cls)`，不要改 `get_benchmark_calculator` 分支（已无分支）
    - `probe.py`：QualityProbe（session jsonl 探测，Quality 的数据源，不是计算器）
  - `pipeline/`：★ 评测收尾编排（`finalize_run` 串起 `metrics_run`（per-task + pooled + run 级）与 `summary`（落盘））；metrics 层保持纯计算（只依赖 models）
  - `comparison.py` / `comparison_report.py`：跨 run 比较（`dumemeval compare`），纯读已落盘产物
- 禁止模块超过 300 行（职责混杂信号）
- 禁止跨层反向依赖（execution 不依赖 adapters；lifecycle 不依赖 execution 的实现，仅依赖协议/常量；metrics 只依赖 models——跨层编排归 pipeline/ 与 report.py）
