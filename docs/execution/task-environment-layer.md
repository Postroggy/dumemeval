# 任务环境层：可插拔的 Agent 环境

环境负责 Agent 的行动空间和资源，记忆由 memory adapter 管理。受管环境、准备检查和运行时控制证据均通过 provider 接口接入，通用执行与报告中不按数据集名称分支。

## 接口

| 接口 | 职责 |
| --- | --- |
| `TaskEnvironmentProvider` | `endpoint` / `usage_hint` / `env_vars` 提供 Agent 可见资源；`create_runtime` 可返回受管运行时。 |
| `TaskEnvironmentProvider.prepare` | 返回 `EnvironmentPreparation` 或其子类。CLI 统一落盘 `preparation.json`，不支持受管准备的 provider 明确报错。 |
| `TaskEnvironmentRuntime` | `open` / `begin_session` / `finish_session` / `close` 管理任务资源、会话权限、执行证据和清理。 |
| `EnvironmentBinding` | 执行器需要的环境变量、只读挂载和追加指令。 |
| `EnvironmentControls` | `task_id`、稳定的 `fingerprint` 输入和 `uncontrolled` 因素；作为 `runtime.json` 的 `controls` 字段。 |

契约见 [`environments.py`](../../src/dumemeval/environments.py)、[`base.py`](../../src/dumemeval/task_environments/base.py) 和 [`models/environment.py`](../../src/dumemeval/models/environment.py)。实现放在数据集自己的 `environment/` 下；HTTP 工具网关和无依赖 Agent 客户端位于通用 `task_environments/`。

## 注册与调用

```python
from dumemeval.environments import HttpTaskEnvironment, register_task_environment

@register_task_environment
class ExampleEnvironment(HttpTaskEnvironment):
    name = "example"
```

配置使用 `task.task_environment: {type: example, base_url: ..., config: {...}}`。
普通 HTTP provider 通过 `SessionRunner` 注入变量与提示；受管 provider 通过 `EnvironmentExecutor` 的任务作用域和会话绑定管理资源。Harbor 接收统一的 mounts、env、instruction。

内置 provider：

- `http`：通用外部 HTTP 服务。
- `webshop`：由使用者启动的官方外部服务，暴露 `/env/*` 协议和动作说明。
- `memoryarena`：五场景受管工具和官方 worker。Shopping 每个购买会话重建环境，其他场景按任务持有环境；详见 [MemoryArena 场景契约](../datasets/memoryarena/README.md)。

## 控制证据

provider 用 `observed_control_keys` 声明必须采集的控制项。受管 MemoryArena 要求 `observed_environment` 和 `observed_agent`；其他 provider 按自己的能力声明。

运行时将稳定输入写入 `EnvironmentControls.fingerprint`，例如官方版本、资源哈希、种子策略。端口、PID、会话令牌和清理状态留在普通运行信息中。报告只对稳定输入计算指纹，不解释具体场景字段。

缺少控制字段、空指纹、重复任务身份或缺少部分任务的运行时证据，都得到 `not-observed`；未控制因素得到 `not-controlled`。旧 `runtime.json` 不会被推测成已验证的新证据。实际执行指令指纹由各执行器记录，与 provider 无关。

## 备选方案与否决理由

| 方案 | 取舍 |
| --- | --- |
| 在 CLI / SessionRunner / 报告中按环境名加分支 | 具体语义泄漏到通用层；改为 provider 方法和类型化证据。 |
| 把官方服务实现放在通用环境目录 | 数据集增加时会不断挤占共享目录；实现归数据集包，协议和工具网关保持共享。 |
| 直接哈希整个 runtime.json | 瞬时端口等字段会造成误报警，具体实现应明确提供稳定控制输入。 |

## 验证

`tests/test_environment_extensions.py` 使用独立的测试 provider，验证 CLI 准备、缺失证据、资源变化、端口变化和未控制因素；`tests/benchmarks/memoryarena/` 验证官方工具生命周期、重置边界、证据和清理。轮次评分仍由数据集 calculator 验证。
