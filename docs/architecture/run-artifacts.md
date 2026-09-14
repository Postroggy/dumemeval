# 结果可追溯与可选 none 适配器

- 状态：implemented
- 源码：`adapters/none.py` · `lifecycle/runner.py` · `provenance.py` · `pipeline/__init__.py`
- 关联：docs/architecture/config-semantics.md · docs/reporting/

## 问题

1. 想跑「框架不接外部 memory」时，yaml 里仍必须填一个具体 adapter，`setup` 还会执行。需要一个 `none`，但不规定谁必须当 baseline。
2. 一次评测的产物散在 experiment_config、summary、per-task、trials、snapshots 里，没有稳定 `run_id`，也没有「这一跑产出了什么」的清单。
3. session 和 Harbor trial 目录只靠命名约定，`SessionOutcome` 不记 `trial_dir`。

## 方案

### 1. `memory.type: none` 可选适配器

`adapters/none.py` 新增 `NoneMemoryAdapter`（所有生命周期 no-op，inject 不写通道）：
- `setup/seed_history/inject/snapshot/observe/teardown` 全部空实现
- `memory_usage_hint()` 返回 None（没有可告知的位置）
- 注册到 `adapters/registry.py`：`"none": ("none", "NoneMemoryAdapter")`
- **契约测试例外**：`test_inject_declares_a_channel` 是「inject 必须写注入通道」的
  硬约束，但 none 的语义就是「不注入」——在 `_NEEDS_SERVICE` 旁加 `_NOOP = {"none"}` 排除。
- **不强制**：test_only + 任意 adapter 仍是合法 baseline；none 只是给「彻底无 memory」
  的用户一个干净表达。baseline 语义（谁当基线）完全由用户 `compare --baseline` 决定。

`memory.type: none` 只表示：**框架不接外部第三方 memory**（不 inject、不算 Quality）。它不表示 agent 没有记忆能力。

hermes / Claude Code 自己带不带 memory，是 runtime 的事。`none` 下面 agent 仍可能读写自己的文件；框架不记这些操作，所以 Trace 的 `memory_tool_used` 会是 False。要看 runtime 自带记忆，需要自己挂目录，或改用 `hermes_builtin`。

谁当 baseline，用 `compare --baseline` 指定。

### 2. 稳定 `run_id`

由实验变量派生（benchmark + data.name + protocol + memory.type + memory_instruction +
agent.runtime），sha256 前缀 12 位 + 可读 slug：

```python
def derive_run_id(cfg: ExperimentConfig) -> str:
    parts = [cfg.task.benchmark or "", cfg.task.data.name if cfg.task.data else "",
             cfg.experiment.protocol, cfg.memory.type,
             cfg.task.memory_instruction, cfg.agent.runtime]
    key = "|".join(parts)
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    return f"{'-'.join(p or 'x' for p in parts)}-{digest}"
```

- 写入 `RunSummary.run_id` → summary.json
- 写入 `RunProvenance.run_id` → experiment_config.json
- `compare` 只要求目录里有 `summary.json`，不看 run_id。同一份 config 换 output 目录，run_id 仍相同。换 protocol 或 memory 后端，run_id 会变。

### 3. `index.json`（结果索引）

`finalize_run` 末尾新增 `write_run_index(...)`，生成 run 级 `index.json`：

```json
{
  "run_id": "...",
  "experiment_name": "...",
  "generated_at": "...",
  "summary": "summary.json",
  "experiment_config": "experiment_config.json",
  "tasks": [
    {
      "name": "locomo_0",
      "backend": "directory-locomo-smoke",
      "result": "locomo_0__directory-locomo-smoke/result.json",
      "report": "locomo_0__directory-locomo-smoke/report.md",
      "sessions": [
        {"session_id": 1, "trial_dir": "trials/dumemeval_locomo_0__session_1",
         "trajectory": "trials/.../agent/trajectory.json", "complete": true}
      ],
      "snapshots": ["snapshots/directory-locomo-smoke"],
      "complete": true
    }
  ]
}
```

- 完整性：每个 task 的 expected trial 目录 / trajectory 是否存在；缺则 `complete: false`
- **只做索引，不管生命周期**：checkpoints / lock 继续由原机制管，不折叠进来

### 4. session ↔ trial 映射显式化

- `SessionOutcome` 加 `trial_dir: str | None = None`
- `SessionRunner` 在 `session_ctx.pop("trial_dir")` 后写回 `outcome.trial_dir`
- `result.session_outcomes` 记录加 `"trial_dir": o.trial_dir`
- index.json 按上面的映射填每 session 的 trial_dir / trajectory 路径

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| manifest.json 管整个生命周期 | 生命周期已被 checkpoints/lock 管着，再折叠一份是重复源；index 只做结果索引 |
| run_id 参与 compare 准入 | compare 就是「比较不同 run」的，run_id 相同与否都不是前提（用户指出，已确认代码） |
| 强制 baseline 不依赖 memory | baseline 语义是实验设计选择，框架只提供表达选项（none adapter），不强制 |

## 语义边界

- `none` 时 Quality 是 0/`None`（没有可观测的外部 memory）。Utility / Efficiency / Trace 照算。
- `run_id` 含 `agent.runtime`：换 agent 就是新 id。
- `index.json` 的 `complete` 只表示文件在不在，不是 session 是否成功。
- 本仓库的 session 是一轮 agent 运行。一篇 locomo 对话是一个 **task**。`index.json` 里的 `tasks[].sessions[]` 指的是本仓库的 session。

## 验证

- `tests/test_none_adapter.py`：生命周期 no-op、不写通道、registry 可创建
- `tests/test_run_index.py`：derive_run_id 稳定、index.json 生成 + 完整性判定
- 全量 `make test` + `make lint`；`make example` mock 跑通
