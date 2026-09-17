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

1. `datasets/benchmarks/<name>.py`：`BenchmarkData.from_raw` + `BenchmarkAdapter.build_tasks` → `list[EvalTask]`。每个问答 session 尽量填 `SessionSpec.query`（不要靠「最后一个 session」对齐）。
2. **docstring 必须带来源 URL**：`Source: <官方仓库 / HF dataset>`，有论文再加 `Paper: <arxiv>`。本地 `Dataset/` 路径不算来源——社区拿不到你的本地盘。
3. `@register_benchmark` 装饰 adapter；在 `datasets/benchmarks/__init__.py` import 该模块。
4. `metrics/<name>.py`：`MetricCalculator` 子类，`kind = "benchmark"`，docstring 写官方实现的文件名 + 关键函数；官方代码未公开时显式标注「自定义，非官方镜像」。
5. 在 `metrics/__init__.py` 的 `register_calculator(...)` 列表里加一行。
6. 在 [docs/datasets/](docs/datasets/README.md) 新增 `<dataset>.md` 并在表格追加一行。
7. **禁止**新增 `scripts/<bench>/*_ingestion.py` 六段流水线。

口径测试用固定 fixture，不要打真实 LLM。

## 加一个评测协议

1. `core/protocol.py`（或独立模块）继承 `EvalProtocol`，实现 `validate` 与需要覆写的 `should_*`。
2. `register_protocol(Cls)`。配置 `experiment.protocol: <name>`。
3. 若需要 runner 里尚不存在的生命周期动作（例如真正的 backup/restore），开 Issue 讨论是否扩展 `SessionRunner` 的钩子——**先不要**在 `run()` 里写死新步骤。

`memory_train_backup_test` 目前是 experimental：对象已注册，行为仍等同 `memory_session_transfer`。

## 加一个任务环境

1. 在 `environments.py` 继承 `TaskEnvironmentProvider`，设 `name`，实现 `endpoint` / `usage_hint` / `env_vars` 三方法。
2. `register_task_environment` 注册。内置两个：`http`（通用模板，暴露 `TASK_ENV_URL`）、`webshop`（对齐 MemoryArena env server 的 `/env/*` 协议）。
3. 任务环境只负责把 endpoint / 动作空间暴露给 agent；环境内行动的评分走对应 benchmark 的官方 calculator，不要在这里写打分逻辑。
4. 参考 `docs/execution/task-environment-layer.md`。纯文本多轮 QA 的适配器（如 travel / search / math）不需要任务环境。

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
