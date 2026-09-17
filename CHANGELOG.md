# Changelog

本项目变更记录，遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 语义。

## [Unreleased]

### Changed
- **CI 口径合一**：本地与 GitHub Actions 都只跑 `make ci`（ruff + mypy + pytest +
  `uv build` + locomo_mini / user_preference mock + smoke 四臂 mock）。workflow
  不再单独写命令。Harbor 真跑与 coverage 仍不进默认门禁。见
  `docs/architecture/ci.md`。
- **`examples/user_preference.yaml`**：bind mount 改为相对路径，去掉本机绝对路径。

### Fixed
- **MemoryAgentBench ingest 粒度**：不再把整段 `context` 塞进一个 session。按官方
  `chunk_text_into_sentences`（tiktoken gpt-4o-mini，默认 chunk_size=4096）切块，
  每块一次 ingest、再逐题 qa（`docs/datasets/memoryagentbench.md`）。此前从
  2026-08-26 接入起就是错误映射。

### Added
- **各数据集官方步骤对照**（`docs/datasets/agentic-eval-pipelines.md`）：MemoryArena /
  MemoryAgentBench / StreamMemBench 等官方流程与本仓库映射、已知偏差；缺口单列。
- **结果可追溯 + 可选 none adapter（设计文档 `docs/architecture/run-artifacts.md`）**：
  - **`memory.type: none`**：所有生命周期 no-op、inject 不写通道的「彻底无 memory」
    baseline 表达（可选，不强制——baseline 语义由用户 `compare --baseline` 决定）
  - **稳定 `run_id`**：由实验变量（benchmark + data.name + protocol + memory.type +
    memory_instruction + agent.runtime）派生，写入 summary.json 与 experiment_config.json；
    同一 config 任何机器/目录跑出同一 run_id，用于结果↔测试追溯，**不参与 compare 准入**
  - **`index.json`（run 级结果索引）**：finalize 生成——run_id、每 task 的
    result/report 路径、session → trial_dir → trajectory 映射、snapshots、完整性标志。
    只做结果索引，不管生命周期（checkpoints/lock 仍由原机制管）
  - **session ↔ trial 映射显式化**：`SessionOutcome.trial_dir` 新字段，
    `result.session_outcomes` 记录 trial_dir，不再靠目录名约定
  - 测试：`tests/test_none_adapter.py` + `tests/test_run_index.py`（run_id 稳定、
    index 完整性判定）
- **配置语义完善（四合一，设计文档 `docs/architecture/config-semantics.md`）**：
  - **数据路径体系统一**：`DatasetSpec.name` 逻辑数据名（`locomo_smoke` /
    `shopping_smoke` / `locomo` / `bundled_shopping`），按 仓库捆绑 data/smoke →
    prepare 缓存 自动解析（`datasets/prepare.py` DATASET_REGISTRY）。`configs/smoke/`
    与 `configs/backends/` 均改用 `name`，配置里不再出现路径；未命中时 loader
    报错并列出可用 name + 下一步提示。doctor 数据检查走同一注册表
  - **sessions 占位显式化**：`SessionConfig.placeholder`——benchmark + data 路径
    必须标 `placeholder: true`（真实 sessions 由适配器生成，防止误改占位指令）；
    非 benchmark 路径禁止 placeholder。全部内置配置/示例已同步
  - **`memory.config` 类型化**：`HermesBuiltinConfig` / `EverOSConfig`（extra=forbid），
    内置 adapter 配错键在加载期报错；社区 adapter 的 config 保持开放 dict
  - **`judging.prompt` 对齐 verifier 注册表**：扩到 5 个模板（补 math_equivalence /
    search_grader），Field 注释写明「benchmark 路径由计算器口径覆盖，透传只带
    model/key/多数票」；新增同步测试防止再漂移
- **配置目录整理**：零依赖示例迁到 `examples/`（`locomo_mini.yaml` /
  `user_preference.yaml`）；真跑对照仍在 `configs/smoke/`；后端/全量实验在
  `configs/backends/`。删除过时兼容入口 `benchmark_*_smoke.yaml`。索引见
  `configs/README.md`、`examples/README.md`
- **架构图**：`docs/dumemeval-eval-loop.html`（评测循环）与
  `docs/dumemeval-layers.html`（分层 / 扩展点 / 对照实验），可切深浅色并导出 PNG/SVG
- **默认 real smoke 对照矩阵**（`configs/smoke/`）：locomo_smoke / shopping 2 回合
  × (`memory_session_transfer` | `test_only`)。`make smoke-mock` 验编排，`make smoke`
  真跑 Harbor。设计文档 `docs/execution/smoke-matrix.md`
- **smoke 数据子集随仓库捆绑（零下载）**：`data/smoke/locomo_smoke.json`（官方
  conv-26 的 session_1..4 + evidence 落在其内的 5 题，5 类别 × 各 1 题全覆盖，
  含 cat5 对抗题）与 `data/smoke/shopping_smoke.jsonl`（bundled_shopping 第 0
  样本前 2 回合）——格式与官方一致（仅截断/取样），有真实 memory 语义，真跑
  smoke 不再需要手动下载 / 改路径。`configs/smoke/*.yaml` 已指向内置子集；
  来源与许可见 `data/smoke/README.md` + `NOTICE`（LoCoMo 为 CC BY-NC 4.0，
  Adapted Material 同许可分发，分数不可引用）
- **`dumemeval prepare` 一键下载完整官方数据**：locomo10 / bundled_shopping 下载
  到 `~/.cache/dumemeval/datasets`（`DUMEMEVAL_DATA_DIR` 覆盖）并重新切出 smoke
  子集。`configs/backends/*.yaml` 改用 `${DUMEMEVAL_DATA_DIR:-~/.cache/...}` env
  模板指向缓存，不再写维护者本机 `../../Dataset/...` 路径。`make prepare` 同效。
  `dumemeval doctor` 新增两项数据检查（捆绑 smoke / 完整数据缓存）。删除
  `prepare.rewrite_smoke_paths`（smoke 内置后不再需要改写 git 内配置）。
  设计文档 `docs/datasets/prepare.md`
- **协议 session 归一化扩展点**：`EvalProtocol.normalize_sessions`（默认恒等），
  `test_only` 覆写为强制 `memory_inject=false`——benchmark 适配器产物硬编码
  `memory_inject=True` 与 test_only 协议此前必然冲突；归一化归协议层，
  `_build_tasks` 构建后先归一化再逐任务校验（此前只校验首个 task）

### Fixed
- **bind mount 相对路径绑不上**：`declare_mount` / HarborBridge 将 host 路径
  `resolve()` 为绝对路径，否则 Docker 静默挂到空目录、跨 session 记忆写不回宿主机
- **LoCoMo 问答泄漏 gold + 多题塞进一个 session**：QA session 改为每题一条、
  instruction 只给问题；中英混答抽出拉丁片段再走官方 token F1
- **Harbor 0.22 no-op verifier schema**：`rewards.note` 字符串导致 TrialResult
  校验失败、agent 已跑完却整 session 判负；现 rewards 只写数字，bridge 在
  `trial.run()` 抛异常时仍从 trial_dir 回收 trajectory
- **load_config 不再读取 ~/.claude/settings.json**：BYOK 只认进程环境变量
  （yaml `${ANTHROPIC_*}`）；Harbor 官方 claude-code 同样从 env exec 进容器，
  评测进程不扫用户家目录
- **shopping 对齐 MemoryArena 官方 webshop**：内置 `webshop` task_environment
  （`search[]`/`click[]`/`Buy Now` + `/env/step` 协议）；适配器不再把商品目录
  摊成纯文本。未启动 env server 时官方 ASIN 分仍为 0（环境缺口，不是样本量）
- **`cfg.judging` 对 benchmark 判分静默失效**：计算器各自 ``LLMJudgeVerifier({"prompt": ...})``
  丢掉用户配置的 judge 模型 / key / 多数票；现经 `metrics/judge.py` 透传，prompt 仍由
  数据集口径决定
- **`SessionConfig.env_extra` 执行层无人消费**：per-session 环境变量静默丢失；现并入
  Harbor `environment.env` 与 MockRunner `mock_agent_env`
- **`task.judgement_mode` 双入口都失效**：benchmark 路径不回填、travel `build_tasks`
  不收 options；现回填到 `task.data`，travel 同时接受 `benchmark_options.judgement_mode`
- **`AgentSpec.temperature` / `max_tokens` 不到 Harbor**：现写入 agent.kwargs
- **`OutputSpec.format` 恒写 json+md**：现按配置落盘
- **mock 与 Harbor 契约不一致**：mock 现在消费 instruction_suffix / task_name /
  agent_memory_dir，缺失挂载路径会报错（与 Harbor bind mount 同语义），并可产出
  `trial_dir` 让 MemoryTransfer.collect 在 mock 下可测
- **benchmark 路径丢 `task.memory_instruction` / `task.task_environment`**：
  适配器按数据集口径构建任务、不感知评测设计层字段，配置里的 proactive/location
  被静默忽略（恒为默认 none）；现由 `_build_tasks` 统一回填。
  设计文档 `docs/lifecycle/memory-instruction-modes.md`（测试 `tests/test_memory_instruction.py`）
- **加载期占位协议校验放行 benchmark**：benchmark 路径 sessions 是占位
  （真实校验在 `_build_tasks` 对适配器产物做），占位不再挡 test_only × benchmark 配置加载
- **`agent_env` / yaml `environment.env` 在 Harbor 路径断链**：各 adapter 注入的
  `session_ctx["agent_env"]`（DUMEMEVAL_MEMORY_DIR / HERMES_* 等）与 yaml
  `execution.environment.env` 此前均未进入 TrialConfig（真跑认证靠宿主 env
  透传的巧合）；现经 `build_trial_config(agent_env=…)` 合并产出
  `environment.env`（agent_env 覆盖 yaml 值），MockRunner 同步消费同契约
- **memory_instruction 模式**（agent-first 缺口 1）：`task.memory_instruction: none / location /
  proactive`——此前 agent 从未被告知 memory 存在，用不用全凭运气。`proactive` 下 instruction
  追加持久记忆位置与「主动读写」要求（adapter 经 `memory_usage_hint` 提供通道描述；
  `test_only` 协议不追加，基线语义不污染）。设计文档 `docs/lifecycle/memory-instruction-modes.md`
- **任务环境层**（agent-first 缺口 3）：`environments.register_task_environment` 扩展点 +
  内置通用 `http` provider——MemoryArena 类 agentic 环境可插拔，agent 经 instruction 后缀
  与 env 变量获知环境交互方式；执行层不感知环境产品。设计文档 `docs/execution/task-environment-layer.md`
- **Utility 回填官方口径**（agent-first 缺口 2）：benchmark 主指标（f1/accuracy/…）≥0.5
  回填 `utility.task_success`（details 标 `source: benchmark_official`）——Utility 段从此
  回答「任务做对了吗」而非「跑完了吗」；`success_rate` 保持完成率语义。
  设计文档 `docs/metrics/utility-official-backfill.md`

### Fixed
- **容器内判分移除（假 success_rate 根因）**：生成的容器 verifier 在空 ground_truth 下
  `"" in answers` 恒真 → reward 恒 1.0 → `utility.success_rate` 恒 1.0（shopping 真跑
  实测）。现在默认 verifier 是 no-op（reward=0 + `scored_on_host` 标记），判分统一在
  host 的 `metrics/`；显式配置 `session.verifier` 才生成容器内判分
- **`SessionOutcome.success` 语义修正**：不再从 Harbor reward（>=0.5）推导——那会把
  「容器跑完了」误报成「任务做对」。新语义：无异常 **且** 采集到 agent 输出；显式配置
  容器 verifier 且 Harbor 返回 `is_success` 时以其为准
- **Dockerfile 去硬编码**：默认最小镜像（`python:3.13-slim`），不再改清华镜像源、不再
  预装 claude-code（agent 安装是 Harbor 的职责）；镜像源 / pip 源 / apt / pip 包 /
  构建命令 / 整份 Dockerfile 均经 `execution.environment` 显式配置；task.toml 资源
  （cpus / memory / storage / agent 超时）同步字段化
- **删 `COPY memory/`**：memory 统一走运行时挂载（`memory_mounts`），build 期 COPY
  会被挂载覆盖
- **去厂商模型默认**：`AgentSpec.model` 默认 None（由引擎决定）、hermes_builtin 无
  model 时明确报错（原先静默回退 DeepSeek-V4-Flash）
- **`DirectoryMemoryAdapter.inject` 死路径**（阻塞开源的缺陷）：它依赖
  `session_ctx["agent_memory_target"]`，但没有任何执行器设置该键——默认 adapter 的
  memory **从未真正注入 agent**，且 mock 与真实「一致地错」，测试全绿。改为统一
  `memory_mounts` 契约（`declare_mount`），`HarborBridge` 与 `MockRunner` 消费同一份声明；
  新增 `tests/test_adapter_contract.py` 强制「inject 必须写注入通道」。
  设计文档：`docs/adapters/memory-injection-contract.md`
- 执行层不再认识产品专有键（`hermes_memory_mount` / `hermes_config_mount` 已移除）

### Changed
- **模块划分清理**（结构重构，行为不变）：`SessionOutcome` 搬进 `models/`，闭合
  「metrics 不依赖 execution」禁区；删掉 `utility/` `efficiency/` 空壳包与 `quality/` 包
  （`QualityProbe` → `metrics/probe.py`）；`dataloader/` 并入 `datasets/loader.py`；
  `cli.py` 拆为 `cli/`（run / inspect / compare），`pipeline.py` 拆为 `pipeline/`
  （finalize_run + metrics_run + summary）。设计文档见 `docs/architecture/module-layout-cleanup.md`

### Added
- **工程规范统一**：硬规范收敛到 `docs/architecture/dev-standards.md`（数据模型 / 类型注解 /
  测试规范 / 依赖 / 版本发布），CLAUDE.md 与 CONTRIBUTING 同源引用；mypy 口径统一为
  src + tests（此前三处不一致）；marker 体系落地（harbor 桥测试打 `integration`）
- **开源协作标准件**：bug report 模板（关空白 Issue）、dependabot、CODEOWNERS、
  CI 增加 `uv build` 与零依赖 mock 冒烟；pre-commit / pytest-cov 进 dev 依赖，
  `make coverage` 与发布检查单（SemVer 精神，1.0 前破坏性变更须有迁移说明）
- **开源就绪**：`NOTICE`（第三方数据集不随仓库分发、口径来源可核对）、`SECURITY.md`
  （威胁模型：agent 执行 / task 定义即代码 / key 脱敏 / 产物含敏感信息）、`CODE_OF_CONDUCT.md`
- **自带迷你数据集** `examples/data/locomo_mini.json` + `configs/example_locomo_mini.yaml`：
  `make example` 零下载零密钥跑通 benchmark 全链路（分数无学术意义，已标注）
- `docs/datasets/README.md` 补数据获取路径（官方来源 → 本地路径 → 改配置）
- **跨 run 比较** `dumemeval compare`：有 `--baseline` 出 Δ（业务问题「接 memory vs 不接」），
  无 baseline 出排名（多 backend 横评）。方向性感知（cost/latency/幻觉率越低越好）、
  缺值记 None 不编造、控制变量不一致（benchmark / judge / task 数 / mock）显式警告；
  纯读 `summary.json` + `experiment_config.json`，不重跑评测
- **Trace 第四维度**：`MetricKind="trace"` + `TraceCalculator`——trace_captured_rate /
  empty_output_rate / error_rate / memory_tool_used（agent 侧读写，setup/inject/snapshot 不计入）
- `RunSummary.metrics`：run 级扁平指标（pooled benchmark + 跨 task 平均），compare 直接 diff
- `models/run.py`：RunSummary / TaskSummary / RunProvenance / RunRef / MetricDelta / RunComparison
  统一进 `models/`；`python -m dumemeval` 入口（`__main__.py`）
- Harbor 相关测试改为 `requires_harbor` skip（只装 `--extra dev` 的贡献者不会看到红）

- **上手路径**：`dumemeval doctor` / `dumemeval list`；`make install doctor mock test`；
  Harbor extra 默认 PyPI（不再强制 `../vendors/harbor`）；`--output` 未指定时用配置 `output.dir`
  报告 / summary 含 mock「不可引用」横幅、Reproduce 代码块、judging.num_runs；
  Quality 明细含 `label` / `runs` / `score_std`，SKIPPED 计入报告

- **计算器注册表** `metrics/registry.py`：加数据集 `register_calculator`，不再改 `get_benchmark_calculator` 的 if/elif
- **开放类型字段**：`MemorySpec.type` / `ExperimentConfig.memory.type` / `experiment.protocol` 改为 `str`，未知值由对应 registry 报错（社区扩展不必改 pydantic Literal）
- `register_protocol` 会 `cache_clear`，避免拿到旧单例

- **LLM-as-Judge 工程健壮性**：`num_runs` 多数票 + 分数均值、瞬时错误指数退避
  （429/5xx/超时，鉴权错误立即抛出）、`skip_failed` 记 SKIPPED、`save_model_input` 留存 judge prompt
- **task 级断点续跑**：`results/checkpoints/<task>.json` 原子落盘；默认跳过已完成 task，
  `--no-resume` 强制重跑。resume 时仍绑定 adapter（Quality 可读已有 memory，不走会清空目录的 setup）
- CLI：`--num-runs` / `--skip-failed-judge` / `--save-model-input` / `--no-resume`
- HTTP / EverOS adapter 写路径走统一 `core.retry`（adapters 不反向依赖 verifier）

- **Hermes 官方内置 memory 适配器**（`type: hermes_builtin`）：对齐 hermes-agent
  `tools/memory_tool.py`（MemoryStore）语义——`$HERMES_HOME/memories/MEMORY.md`
  （agent 笔记，上限 2200 字符）+ `USER.md`（用户画像，上限 1375 字符）双文件，
  `§` 分隔条目（strip/去空/去重保序）、原子写盘、session 启动冻结快照注入
  （`═` 分隔线 + 标题[百分比 — chars] 格式）、`add`/`replace`/`remove` 写操作
  （唯一子串匹配，超限/重复/多匹配拒绝）、`seed_history` 从 task.data 灌入历史
- **移除误导性的 `type: hermes`（memory-tencentdb）适配器**：memory-tencentdb 是
  腾讯第三方插件（TencentDB-Agent-Memory 的 hermes-plugin），不是 Hermes 官方
  memory；相关文件（adapters/hermes.py、test_hermes_adapter.py、
  benchmark_locomo_hermes.yaml）已删除
- `BaseMemoryAdapter.seed_history(task)`：评测前历史对话注入钩子（runner 在
  setup 后调用），adapter 从 `task.data["conversation_sessions"]` /
  `["history_messages"]` 提取对话灌入
- `benchmark_options` 配置项：benchmark 适配器参数（如 `locomo subset: 1` 取
  1 个对话做 smoke test）；`MemorySpec`/`MemoryBackendSpec` 新增 `team_id`/`agent_id`
- LoCoMo 适配器 `build_tasks(subset=...)` 支持截取前 N 个对话；answer/sample_id
  兼容 int 类型（真实数据含数字答案）
- smoke test 配置示例 `configs/benchmark_locomo_hermes_builtin.yaml`（LoCoMo
  subset=1 × Hermes 官方内置 memory，官方 F1 + 按类 accuracy）
- 统一指标层 `metrics/`：`MetricCalculator` 协议 + `MetricsAggregator`（一次评测一份扁平 `result.metrics`）
- 官方 LoCoMo F1（normalize + Porter stemmer + Counter，对齐 snap-research/locomo / Harbor verifier）
- LoCoMo 按类 accuracy（multi_hop / temporal_reasoning / open_domain / single_hop）
- **第二批数据集适配（14 个）**：
  - PersonaMem：MCQ 选项字母匹配 accuracy（官方 inference.py extract_answer，纯确定性）
  - ScriptMem：single/multi/ordering 精确字母匹配 accuracy（官方 score_mcq.py，纯确定性）
  - memsim/MemDaily：选项字母 exact match + recall@step（官方 TimeFlow.py，纯确定性）
  - EverMemBench-Dynamic：MC 规则判分（官方 _parse_mc_answer）+ OE LLM judge
  - Locomo-Plus：6 类 LLM judge 评分（correct=1/partial=0.5/wrong=0，官方 prompt.py）
  - MemoryAgentBench：按能力路由（AR/CR substring_exact_match、LRU/TTL exact_match、Recsys Recall@5、LLM judge）
  - LongMemEval：5 类 judge 模板 + abstention（_abs 后缀单独计分，官方 evaluate_qa.py）
  - CL-bench / CL-bench-Life：Solving Rate（LLM judge 按 rubrics 全有或全无）
  - Memora：FAMA = max(0, MPA − λ(1−FAA))（官方 model_based_evaluator.py）
  - PerLTQA：EM + token F1（⚠️ 官方评测代码未发布，适配层自定义判分）
  - BEAM：LLM judge 按 rubric 打分平均（官方 compute_metrics.py）
  - HaluMem：三阶段（integrity recall / interference accuracy / update 分类 / QA 分类）
  - MemoryCD：MAE/RMSE/ROUGE-L/NDCG@5/Recall@5（官方 eval_core.py，纯确定性）
  - MemoryBench：28 子集按子集路由（Locomo F1 / DialSim exact+judge / LexEval ROUGE-L / 生成型 judge）
- `LLMJudgeVerifier.verify_with_prompt`：暴露原始 prompt 入口，供数据集自定义 judge 模板
- 依赖新增：`pyarrow`（parquet 读取）、`datasets`（HF arrow 读取）
- MemoryArena travel 官方 slot 判定 + `judgement_mode`（hint / answer / none）
- MemoryArena shopping 适配：官方 `match_ground_truth`（ASIN 精确匹配）/ `overall_success` / `attribute_match`
- MemoryArena progressive_search 适配：官方 GRADER_TEMPLATE + `parse_judge_response` → `accuracy`
- MemoryArena formal_reasoning math/phys 适配：官方 yes/no 数学等价 judge → `is_correct`
- StreamMemBench 适配：官方四指标 fidelity / initial_evidence_use / feedback_incorporation / followup_reuse
- verifier 新增官方判分 prompt：`math_equivalence`（math_env.judge）、`search_grader`（GRADER_TEMPLATE）
- `SessionSpec.query` 字段：session 显式声明对应的 benchmark 问题，消除位置对齐猜测
- benchmark 示例配置 `configs/benchmark_shopping.yaml`
- CLI benchmark 路径：`task.benchmark` + `task.data` 时自动加载数据集并经适配器
  `build_tasks` 生成任务（覆盖配置占位 sessions），默认评测第一个样本

### Changed
- Quality / Utility / Efficiency 计算器迁入 `metrics/`，原模块路径保持再导出
- Benchmark adapter 的 `evaluate()` 委托统一指标层，不再手写玩具 F1
- `_apply_bundle`：bundle 完整定义本次结果，缺 key 回默认值而非沿用旧值（消除幽灵数据）
- `update_accuracy` 改为 `None = 未测`，报告显示 n/a 而非误导性 0.000
- mypy 覆盖范围扩展到 `tests/`（src + tests 全部 strict 通过）

### Fixed
- HarborBridge 现在从 `trial_dir/agent/trajectory.json`（ATIF）提取 agent 最终输出写入
  `SessionOutcome.observation`，并通过 `compute_token_cost_totals()` 回填 tokens——
  此前真实 Harbor 执行下 observation 恒为空，所有依赖输出的 benchmark 指标会算 0 分
- `outputs_from_result` 优先按 `session.query` 精确匹配（travel 的注入轮等
  session 数 != question 数 场景不再错位），位置切片仅作兼容兜底
- search/math 计算器无注入 judge 时懒加载 `LLMJudgeVerifier`（官方 prompt）真实判分，
  不再把"没配 judge"静默判错
- README 修正：移除不存在的 `--harbor` flag（由 `execution.engine` 决定）；更新目录树
- harbor 依赖移出核心依赖（第三方 clone 后 `uv sync` 不再因仓库外路径失败），
  改为 optional extra `harbor`
- CLI：mock 模式与"observation 全空"场景输出解释性警告，不再静默给出全 0 报告

## [0.2.0] - 2026-08-24

### Added
- uv 管理项目（`uv.lock`、`[tool.uv]`、src 布局 `src/dumemeval/`）
- 所有数据模型改用 pydantic BaseModel（models/executor/verifier）
- CLAUDE.md 项目规范（强制 pydantic、类型注解、测试）
- LLM judge 支持 OpenAI/Anthropic 双 provider（oneapi-comate 网关验证）
- HarborBridge 单元测试（8 个：trial 解析/memory 注入/收集/流程）
- 工程化：CI（GitHub Actions）、pre-commit、LICENSE、.python-version

### Changed
- SessionExecutor 协议抽象（MockRunner/HarborBridge 统一契约）
- session_ctx 贯穿所有 session（memory 注入 env 正确传递）
- Quality precision 公式修正（按记忆条目算，可检测 hallucination）

### Fixed
- Harbor 对接兼容：TrialConfig.task.path、org/name 格式、verifier_result.rewards
- base_url 自动补 /v1（oneapi 网关）、reasoning_content fallback（DeepSeek 推理模型）
- 跨 session memory 传递（bind mount + memory_dir 注入）

## [0.1.0] - 2026-08-24

### Added
- 框架骨架：models/adapters/dataloader/orchestration/quality/utility/efficiency
- Mock 模式全链路 + Harbor trial 全链路（nop agent 验证）
- claude-code agent 端到端（success_rate=1.0）
