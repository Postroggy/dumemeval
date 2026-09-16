# 贡献指南

先读 [GOVERNANCE.md](GOVERNANCE.md)（目标、分层、扩展点、禁区）。本页是操作清单。

## PR 流程：设计文档先行（无例外）

```
写设计文档（docs/<模块>/<功能>.md）→ 实现 → 测试 → 提 PR 前回头更新文档 → 提 PR
```

**任何 PR 都必须有设计文档**——新功能、重构、修 bug、改配置、动 CI、改文档结构，都算。没有文档的 PR 不予 review。

理由：review 要能对着「你想解决什么、为什么这样解决」判断，而不是逐行猜意图。改动越小，文档越短——不是免写。

| 改动类型 | 文档去哪 | 篇幅参考 |
|---|---|---|
| 新功能 / 新扩展点实现 | `docs/<模块>/<功能>.md` 新增一篇 | 完整（含备选方案） |
| 修 bug | 更新受影响功能那篇的「语义边界」或「未完成」；无对应文档则新建 | 几行：什么前提下会错、为什么之前没发现 |
| 重构（行为不变） | 更新对应模块文档的「方案」段 | 短：为什么改结构、为什么不改行为 |
| 配置 / CI / 工程 | `docs/architecture/` 对应篇 | 短 |
| 只改文档 | 就在被改的那篇里说明改动缘由 | 一句话 |

提 PR 前 double check：文档写的方案 = 代码实际做的事。不一致时改文档，别让下一个人被误导。

## 怎么提 PR

1. fork 仓库并 clone；没有 fork 权限就先开 Issue。
2. 从最新的 `master` 切分支：`git checkout -b feat/<short-name>`。
3. 写设计文档，再实现和测试。本地过 `make ci`（与 GitHub Actions 同口径）。
4. commit 信息带前缀：`feat:` / `fix:` / `docs:` / `refactor:` / `test:`。
5. push 后开 PR。描述里贴设计文档链接和测试摘要。
6. 按 review 改完再 push，不用重开 PR。

提 PR 即表示贡献按本仓库的 Apache-2.0 授权（见 [LICENSE](LICENSE) 第 5 条），除非你标明「Not a Contribution」。

## 开发环境

加 adapter / 数据集 **不需要** Docker、Harbor、API key。

```bash
make install      # 含 pre-commit install（格式门禁自动生效）
make example      # 自带迷你数据集，验证装完能跑
make ci           # 与 GitHub Actions 同口径（lint + test + build + mock smoke）
make coverage     # 覆盖率报告（不进 CI 门禁）
```

仅支持 Python 3.12+（Harbor 的要求）。

发布维护者看 dev-standards.md 的「版本与发布」检查单（SemVer 精神，1.0 前次版本可含破坏性变更，须有 CHANGELOG 迁移说明）。

工程硬规范（数据模型 / 类型注解 / 测试 / 依赖 / 版本发布）统一见 [docs/architecture/dev-standards.md](docs/architecture/dev-standards.md)——与 `CLAUDE.md`（`AGENTS.md` 是它的符号链接）同源，一处维护。

## 加一个 Memory 后端

1. `src/dumemeval/adapters/<name>.py` 实现 `BaseMemoryAdapter`（五个生命周期方法）。
2. **`inject` 必须写注入通道**：目录/文件型用 `declare_mount(session_ctx, host, container)`，服务型写 `session_ctx["agent_env"]`。两者都不写 = memory 到不了 agent（静默失败），`tests/test_adapter_contract.py` 会红。契约见 [docs/adapters/memory-injection-contract.md](docs/adapters/memory-injection-contract.md)。
3. `register_adapter("<name>", "<name>", "<ClassName>")`（内置的写在 `adapters/registry.py` 的 `_ADAPTER_REGISTRY`）。
4. 配置：`memory.type: <name>`。**不必**改 `MemorySpec` / `ExperimentConfig` 的类型字段（已改为开放 `str`，未知类型由 registry 报错）。
5. 测试：生命周期（setup 清空、inject、snapshot）+ 至少一种失败路径。
6. **禁止**在 `lifecycle/runner.py` 或执行器里加 `if type == "<name>"`。

参考：`adapters/directory.py`（目录型 + 挂载）、`adapters/http.py`（wrap/add 协议）、`adapters/everos.py`（真实产品 API）。

## 加一个数据集

1. 多场景或自带环境的数据集族放在 `src/dumemeval/benchmarks/<name>/`，内部按 `datasets/`、`metrics/`、`environment/` 分工；简单适配器也可继续使用 `datasets/benchmarks/<name>.py`。`BenchmarkData.from_raw` + `BenchmarkAdapter.build_tasks` → `list[EvalTask]`，问答 session 填 `SessionSpec.query`。
2. **docstring 必须带来源 URL**：`Source: <官方仓库 / HF dataset>`，有论文再加 `Paper: <arxiv>`。本地 `Dataset/` 路径不算来源——社区拿不到你的本地盘。
3. 用 `@register_benchmark` 注册 adapter；在 `datasets/benchmarks/__init__.py` 导入模块或集成包，沿用已有初始化方式。包导入不应启动服务或加载可选模型 SDK。
4. 在数据集自己的 `metrics/` 实现 `MetricCalculator`，`kind = "benchmark"`；docstring 写官方实现的文件名 + 关键函数，官方代码未公开时标注「自定义，非官方镜像」。
5. 用 `register_calculator(Cls, *aliases)` 注册计算器和别名；简单计算器继续在 `metrics/__init__.py` 注册，集成包可在自己的 `metrics/__init__.py` 注册，由 `metrics/benchmarks/__init__.py` 导入。无需修改通用注册表的查询函数。
6. 测试与 fixture 放在 `tests/benchmarks/<name>/`，设计与验收材料放在 `docs/datasets/<name>/`，并更新[数据集索引](docs/datasets/README.md)。目录和兼容例子见 [MemoryArena](docs/datasets/memoryarena/layout.md)，注册方式见[原框架复用](docs/datasets/memoryarena/framework-reuse.md)。
7. **禁止**新增 `scripts/<bench>/*_ingestion.py` 六段流水线。

口径测试用固定 fixture，不要打真实 LLM。

## 加一个评测协议

1. `core/protocol.py`（或独立模块）继承 `EvalProtocol`，实现 `validate` 与需要覆写的 `should_*`。
2. `register_protocol(Cls)`。配置 `experiment.protocol: <name>`。
3. 若需要 runner 里尚不存在的生命周期动作（例如真正的 backup/restore），开 Issue 讨论是否扩展 `SessionRunner` 的钩子——**先不要**在 `run()` 里写死新步骤。

`memory_train_backup_test` 目前是 experimental：对象已注册，行为仍等同 `memory_session_transfer`。

## 加一个任务环境

1. 在数据集的 `environment/` 中继承 `TaskEnvironmentProvider`，设 `name`，实现 `endpoint` / `usage_hint` / `env_vars`。通用协议保留在 `environments.py` 和 `task_environments/base.py`。
2. 用 `@register_task_environment` 注册；内置实现由 `environments.py` 在契约与注册函数定义完毕后导入。已有 `http`、外部 `webshop` 和受管 `memoryarena` 三种 provider。
3. 受管环境实现 `create_runtime` 及 `TaskEnvironmentRuntime` 生命周期，按需实现 `prepare`。评分仍由对应 benchmark calculator 负责。
4. 通过 `observed_control_keys` 声明必须观测的控制项，在 `runtime.json` 中写 `EnvironmentControls`。选择稳定字段，声明未控制的因素；通用报告不解释数据集的内部字段。
5. 参考[任务环境层](docs/execution/task-environment-layer.md)。环境资源与记忆各自管理；不得在 SessionRunner 增加数据集分支。

## PR 检查单

- [ ] **设计文档已写并与实现一致**（`docs/<模块>/<功能>.md`）——任何 PR 都要，无例外
- [ ] 文档里有「备选方案与否决理由」（新功能 / 重构必填）
- [ ] 只碰对应层；禁区文件无无关 diff
- [ ] 新公共类型是 pydantic `BaseModel`
- [ ] 数据集 PR：docstring 有 `Source:` URL，`docs/datasets/` 已更新
- [ ] 任务环境 PR：`register_task_environment` 已注册，docstring 说明协议 / 动作空间
- [ ] `make ci` 绿（与 GitHub Actions 同口径：ruff + mypy + pytest + build + mock smoke）
- [ ] 若改指标语义，在 GOVERNANCE「勿过度解读」补一句

## 提问

- 用法、配置、数据集：先看 [docs/](docs/README.md)，没有答案就开 Issue（有模板就选对应模板）。
- 报 bug、加 adapter / 数据集：用 `.github/ISSUE_TEMPLATE/`。
- 协作规范：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
- 安全漏洞：不要开公开 Issue 写细节，见 [SECURITY.md](SECURITY.md)。
