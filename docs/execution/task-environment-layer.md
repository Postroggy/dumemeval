# 任务环境层：可插拔的 agentic 环境

- 状态：implemented（扩展点 + 内置 `http` / `webshop` provider）；官方 env server 由使用者启动
- 源码：`src/dumemeval/environments.py` · `src/dumemeval/core/config.py`（TaskEnvSpec）· `src/dumemeval/lifecycle/runner.py` · `src/dumemeval/execution/task_dir.py`

## 问题

agent-first 的最后一道缺口：MemoryArena shopping 任务是 **agentic 的**——agent 在 webshop 环境里搜索、行动、观察反馈。本框架此前把这类任务摊平成纯文本 instruction，agent 退化成「拿长文本的 LLM」：shopping 真跑时 agent 自己报告「环境里没有商品目录」。

当前只有 shopping 接入环境；travel / search / math 适配器不设 `task_environment`，仍是纯文本多轮 QA（见「语义边界」）。

没有环境层，「agent 在环境里行动」只是 README 里的形容词。

## 方案

与 memory adapter 同范式的扩展点：

```python
from dumemeval.environments import register_task_environment

@register_task_environment
class WebshopEnvironment(TaskEnvironmentProvider):
    name = "webshop"
    def endpoint(self, spec): ...      # 环境服务地址
    def usage_hint(self, spec): ...    # 告诉 agent 环境能做什么、怎么交互
    def env_vars(self, spec): ...      # 注入 agent 环境的变量（如 TASK_ENV_URL）
```

- 配置：`task.task_environment: {type: webshop, base_url: ..., config: {...}}`
- `lifecycle.SessionRunner` 在 inject 阶段消费 provider：env 变量并入 `agent_env`，`usage_hint` 并入 `instruction_suffix`（与 memory 指令同通道）
- 内置 `http` provider（通用）：把 `base_url` 暴露为 `TASK_ENV_URL` + 通用使用提示，供自建环境 server 直接接入
- **执行层不感知环境产品**——provider 在 lifecycle 消费，Harbor 只看到最终的 mounts/env/instruction

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 框架内置 webshop/travel 环境 server | 每个环境是独立服务（状态、评分、HTTP），体量是本框架的两倍；这是社区插件，框架只定契约 |
| 用 SandboxExecutor 让 agent 自己起环境容器 | 复杂度爆炸（端口、健康检查、生命周期管理），且 MemoryArena 官方已是独立 server，接过来就行 |
| 环境信息只写 env 不进 instruction | agent 不会读不存在的文档；环境可交互性必须显式告知（同 memory instruction 的教训） |
| 把 provider 塞进 `adapters/` | memory 与 task environment 是两个被测维度（一个管记忆、一个管行动），目录上混层会让贡献者找错扩展点 |

## 语义边界

- 当前内置且仅有 `http` / `webshop` 两个 provider；`memoryarena_shopping` 适配器
  在 `build_tasks` 写死 `task_environment: {type: webshop, base_url: None, config:
  {env_name: webshop}}`，configs 的 yaml 再覆写 `base_url`（默认
  `${WEBSHOP_ENV_URL:-http://127.0.0.1:8005}`）——购物任务实际接框架内置
  webshop provider，指向自建/官方 webshop env server 端点
- `memoryarena_travel` 及 search / math 类适配器不设 `task_environment`：纯文本
  多轮 QA，无环境接入；行动打分仍走各 benchmark 官方口径（shopping 的 ASIN
  exact match / overall_success / attribute_match 在
  `metrics.benchmarks.memoryarena_shopping`）
- 框架只负责把环境**暴露给 agent**（endpoint / hint / env）；环境内的行动评分走各 benchmark 的官方口径
- `http` provider 的通用 hint 不描述具体动作空间——真正的 provider 应覆写 `usage_hint`（如「用 search[商品名] 搜索，用 buy[asin] 购买」）
- 环境服务的可用性由使用者保证；框架不做健康检查（后续可加 preflight）

## 验证

- `tests/test_environments.py`：注册自定义 provider → `get_task_environment` 取回；未注册类型报错并列出可用项；http provider 的 endpoint/hint/env；SessionRunner 集成——配置了 task_environment 的 task，`session_ctx` 里出现 env 变量与 instruction suffix

## 未完成

- webshop 官方 env server 仍由使用者启动（`python env/env_server.py`，默认 :8005；
  商品库见 MemoryArena `setup_web_shopping.md`）。框架内置 `webshop` provider
  只暴露协议与动作空间，不内嵌商品库
- 环境健康检查（preflight ping）
- 环境状态的生命周期管理（reset / teardown 钩子）
