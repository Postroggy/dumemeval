# Memory 注入契约：统一 `memory_mounts`

- 状态：implemented
- 源码：`src/dumemeval/adapters/base.py` · `src/dumemeval/adapters/directory.py` · `src/dumemeval/adapters/hermes_builtin.py` · `src/dumemeval/execution/harbor_bridge.py` · `src/dumemeval/execution/mock.py`
- 关联：修复 `DirectoryMemoryAdapter.inject` 死路径

## 问题

### 1. 默认 adapter 的注入路径从未执行

`DirectoryMemoryAdapter.inject` 依赖 `session_ctx["agent_memory_target"]`：

```python
target = session_ctx.get("agent_memory_target")
if target is None:
    self._record("inject", session.id, content="(skip: no target ...)")
    return
```

而 `HarborBridge` 与 `MockRunner` **都不设置这个键**，`SessionRunner` 也不设置。结果：`type: directory`（默认值，也是 quickstart 配置用的类型）的 memory **永远不会进入 agent 环境**。

实测证据（shopping 真跑）：

```
memory_ops: inject → "(skip: no target for session 1)"
```

session 2 的 agent 明确报告「没有 Product 1 的记录」——跨 session 记忆链断了，而这条链正是本框架的被测对象。

**为什么测试没抓到**：mock 也不设这个键，两边行为「一致地错」，既有测试全绿。

### 2. execution 层硬编码了产品特定键名

`HarborBridge` 里有：

```python
hermes_mount = session_ctx.get("hermes_memory_mount")
hermes_cfg = session_ctx.get("hermes_config_mount")
```

虽然没 `import adapters`（技术上没破禁区），但执行层认识 `hermes_*` 这种产品名——精神上已经违反「执行器不感知 memory 产品」。每加一个需要挂载的 adapter，就要在 execution 里加一个 `if`，这正是我们要避免的分支树。

## 方案

一个通用契约替代所有产品特定键：

```python
session_ctx["memory_mounts"]: list[MemoryMount]   # (host_path, container_path)
```

| 角色 | 做什么 |
|---|---|
| adapter.inject | `declare_mount(session_ctx, host, container)` 追加声明 |
| HarborBridge | 只读 `memory_mounts` → bind mounts（host 路径必须是绝对路径，相对路径 Docker 绑不上）；`agent_env` + `session.env_extra` 进 TrialConfig.environment.env |
| MockRunner | 同契约：校验 host 路径存在（缺失则报错）、记录注入文件清单、合并 env_extra、消费 runner 级通道并可产出 `trial_dir` |

`declare_mount` 放在 `adapters/base.py`（adapter 侧的共享工具），`MemoryMount` 模型放 `models/`（两层都要用）。

### 各 adapter 的映射

| adapter | 声明的挂载 |
|---|---|
| `directory` | `(spec.path, "/app/memory")` |
| `hermes_builtin` | `(memories 目录, "/tmp/hermes/memories")` + `(config.yaml, "/tmp/hermes/config.yaml")` |
| `http` / `everos` | 无挂载（走 `agent_env`，不变） |
| `none` | 无挂载、无 env 注入——inject 刻意不写任何通道（no-op），见「语义边界」 |

### MockRunner 为什么也要读

mock 与真实**必须消费同一个契约**，否则「注入通道断了」这类 bug 依旧只在真跑时暴露。MockRunner 把每个挂载的 host 侧文件清单写进 `session_ctx["mock_injected_files"]`，让契约测试能在无 Docker 环境断言「memory 真的传到了执行器」。

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 让 `SessionRunner` 设置 `agent_memory_target` | 只修 directory 一家；`hermes_*` 的产品硬编码仍在，下一个 adapter 继续加 `if` |
| `HarborBridge` 里补 `if type == "directory"` | 正是 GOVERNANCE 禁止的分支树；execution 会越来越懂 memory 产品 |
| adapter 直接返回 mount 列表（改 `inject` 签名） | `inject` 已通过 `session_ctx` 传递 env，再加返回值形成两条通道，调用方要合并两处 |
| 保留 `agent_memory_target` 作为兼容别名 | 尚未发布，无外部使用者；留着等于保留一条永不执行的死路径 |
| 只修 bug 不加契约测试 | mock 与真实的行为差是这个 bug 能藏住的根因，不加测试等于允许它复发 |

## 语义边界

- `memory_mounts` 只表达「host 目录 → 容器目录」。agent 是否真的**读**了这些文件，由 Trace 的 `memory_tool_used` 回答，不在本契约范围
- `memory.type: none` 只表达一件事——框架不接入任何外部第三方 memory（setup / seed / inject / snapshot / observe 全部 no-op，inject 刻意不写 `memory_mounts` / `agent_env` 任何注入通道）。它**不代表**「被测 agent 没有记忆能力」：agent runtime（hermes / Claude Code 等）自身是否带原生 memory 是 runtime 的属性。none 下 Quality 为 0/None（无可观测的外部 memory），Utility / Efficiency / Trace 照算；谁当 baseline 由 `dumemeval compare --baseline` 决定，none 不强制
- MockRunner 记录的是「host 侧有哪些文件可注入」，不模拟容器内可见性——真实挂载语义仍需 Harbor 验证
- `MemoryTransfer` 的 auto-memory 收集通道（`agent_memory_dir` → Harbor `agent.kwargs.memory_dir`）保持不变：它解决的是「agent 自己写的 memory 如何跨 session 传递」，与 adapter 主动注入是两件事

## 验证

- `tests/test_adapter_contract.py`：对每个内置 adapter 跑 `setup → inject`，断言**注入通道非空**（`memory_mounts` 或 `agent_env` 至少一个被写；`none` 是唯一例外——它刻意不写任何通道，测试对它放行），directory / hermes_builtin 断言具体挂载目标
- `tests/test_orchestration.py`：mock 全链路下 `mock_injected_files` 能看到 memory 文件
- 既有测试全部保持绿（不改断言换绿）

## 未完成

- 未校验容器内挂载点冲突（两个 adapter 声明同一 container 路径时后者覆盖前者）
- MockRunner 不模拟容器文件系统，只做 host 侧清单
