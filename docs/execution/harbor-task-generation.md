# Harbor task 目录生成：只做适配，不做判分

- 状态：implemented
- 源码：`src/dumemeval/execution/task_dir.py` · `src/dumemeval/execution/harbor_bridge.py` · `src/dumemeval/core/config.py`
- 关联：`docs/adapters/memory-injection-contract.md`（挂载契约）

## 问题

`TaskDirGenerator` 的职责本应是「把 `SessionSpec` 翻译成 Harbor 要的 task 目录」，但它顺手接管了判分和环境构建，产生 5 个缺陷：

### 1. 生成的 rule verifier 在空 ground_truth 下恒判成功

```python
gt = ""                               # SessionSpec.verifier 为 None 时写入空串
ok = gt.lower() in answers.lower()    # "" in 任何字符串 → True
```

benchmark 路径下 `SessionSpec.verifier` 基本都是 `None`，所以容器里的 verifier **恒返回 reward=1.0**，`SessionOutcome.success` 由 `reward >= 0.5` 推出 → `utility.success_rate` 恒为 1.0。

实测：shopping 真跑 `success_rate=1.000` 而官方 `overall_success=0`。**报告里有一个指标系统性说谎**，比 memory 注入那个 bug 更严重。

### 2. verifier 依赖 `/workspace/answers.txt`，但没人告诉 agent 写它

`instruction.md` 只写 `session.instruction`（数据集原文），不会提这个文件。agent 永远不写 → verifier 读到空 → 叠加问题 1，两个 bug 互相掩盖。

### 3. 判分逻辑在容器里重写一遍（Python 源码字符串）

我们已有完整 `verifier/`（双 provider judge、多数票、重试、parsers）与 `metrics/`（各数据集官方口径）。`task_dir.py` 里两个字符串模板实现了简化版判分，它们：不过 ruff/mypy/测试；口径与 host 不一致（只看 `"CORRECT" in raw`）；**产出根本没被使用**——评测结论走 host 的 `metrics/`。

社区第一个问题会是「为什么有两套 judge，哪个是真的」。

### 4. Dockerfile 硬编码清华镜像源与 claude 安装

3 处 `mirrors.tuna.tsinghua.edu.cn` + `downloads.claude.ai` bootstrap。对内网友好，对海外贡献者是直接变慢或失败；且写死了「agent 一定是 claude-code」。

### 5. `COPY memory/` 与 bind mount 语义打架

Dockerfile 在 build 时 `COPY memory/ /app/memory/`，而挂载契约在**运行时** bind mount 同一路径——挂载会盖掉 COPY，两套机制其中一套是死的。

## 方案

### 判分归位：容器只做 no-op

评测结论本来就在 host 算（`observation` 从 trajectory 提取 → `metrics/` 算官方口径）。容器 verifier 改为写一份显式 no-op reward：

```json
{"total": 0.0, "scored_on_host": 1.0}
```

配套改 `SessionOutcome.success` 的语义：**不再从 Harbor reward 推导**，改为「trial 无异常 且 采集到 agent 输出」。理由：Harbor reward 在我们的用法里没有判分含义，用它推 success 等于把「容器跑完了」误报成「任务做对了」。

`session.verifier` 显式配置时（rule/llm_judge）仍生成真实 verifier——那是用户主动要容器内判分，不是默认路径。

### 环境可配置：`EnvironmentSpec` 增加构建参数

| 新字段 | 作用 | 默认 |
|---|---|---|
| `base_image` | Dockerfile `FROM` | `python:3.13-slim` |
| `apt_mirror` | 替换 Debian 源域名 | `None`（不改源） |
| `pip_index_url` | pip 源 | `None`（用官方） |
| `pip_packages` | 额外 pip 包 | `[]` |
| `apt_packages` | 额外 apt 包 | `[]` |
| `setup_commands` | 任意构建期命令（预装 agent CLI 等） | `[]` |
| `dockerfile` | 直接给整份 Dockerfile 路径，完全接管 | `None` |

默认产物是最小 Dockerfile（`FROM python:3.13-slim` + WORKDIR），不预装任何 agent——**agent 安装是 Harbor 的职责**（它的 `BaseInstalledAgent` 就干这个）。国内用户在配置里写镜像源即可。

### task.toml 资源可配置

`timeout_sec` / `cpus` / `memory_mb` / `storage_mb` 从写死改为 `EnvironmentSpec` 字段。

### 删 `COPY memory/`

memory 统一走运行时挂载（`memory_mounts` 契约），不再在 build 期烘进镜像。

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 保留容器判分，只修空 GT（改成「空 GT 时判失败」） | 容器判分本身无人使用，修它是维护一条死路径；且「空 GT 判失败」会让所有 benchmark 恒 success=false，同样是假信号 |
| 让 instruction 追加「请写 /workspace/answers.txt」 | 改写数据集原文 = 污染任务语义（GOVERNANCE 明令 instruction 用原文）；且 observation 已能从 trajectory 拿到，不需要额外文件通道 |
| `SessionOutcome.success` 保留 reward 推导，只把 no-op reward 设为 1.0 | 仍是假信号，只是换个方向骗人 |
| Dockerfile 用 Jinja 模板文件 | 引入模板引擎依赖，而拼接需求只有「按字段追加几行 RUN」；`dockerfile` 字段已覆盖复杂场景 |
| 保留清华源做默认，加开关关掉 | 默认值应对所有人成立；地域优化属于用户配置，不是框架默认 |
| 把容器路径（`/app/memory` 等）也做成配置 | 这些是 adapter 与其目标 agent 之间的约定（如 `$HERMES_HOME/memories`），不是用户选项；已收敛为各 adapter 的模块常量 |

## 影响面

- 修改：`src/dumemeval/execution/task_dir.py`（删两个 verifier 模板、Dockerfile 改为按配置拼接、资源字段化）、`src/dumemeval/execution/harbor_bridge.py`（success 语义）、`src/dumemeval/core/config.py`（`EnvironmentSpec` 扩字段）、`src/dumemeval/execution/trial_config.py`（透传资源）
- **行为变更**：`SessionOutcome.success` 不再由 Harbor reward 决定；默认镜像不再预装 claude-code、不再改镜像源
- 迁移：现有配置若依赖预装 claude，需显式写 `setup_commands`；`configs/backends/locomo_hermes_builtin.yaml` 已用 `docker_image` 走预构建镜像，不受影响

## 语义边界

- `SessionOutcome.success` = 「这个 session 跑完并产出了可判分的输出」，**不代表任务做对**。任务对错看 `metrics/` 的官方口径与 Quality/Utility
- `reward` 字段保留（Harbor 原样透传），但默认路径下恒为 0.0 且不参与 success 判定；用户显式配 `session.verifier` 时才有意义
- 框架不校验 `setup_commands` 的内容——那是用户对自己环境的声明

## 验证

- `tests/test_task_dir.py`：默认 Dockerfile 不含镜像源/claude 安装/COPY memory；配置了 `apt_mirror`/`pip_index_url`/`setup_commands` 时正确出现；`dockerfile` 字段接管时不生成
- `tests/test_task_dir.py`：默认 verifier 是 no-op（不读 answers.txt、reward 标 `scored_on_host`）；显式配 verifier 时生成真实判分
- `tests/test_harbor_bridge.py`：success 由「无异常 + 有 observation」决定，空 observation → success=False

## 未完成

- 容器内判分（`session.verifier` 显式配置路径）仍是简化实现，与 host judge 口径不完全一致；建议后续直接复用 host judge 或标为 deprecated
- `setup_commands` 无缓存分层优化（每次改动都会让 Docker layer 失效）
