# Quick Start

一次评测由 YAML 配置描述 benchmark、agent、memory、session、执行引擎和输出目录。

## Mock

```bash
uv sync --extra dev
uv run dumemeval run --config examples/locomo_mini.yaml --mock --no-resume
```

使用仓库自带迷你数据，不需要下载数据、Docker、Harbor 或 API key。mock 只验证编排，分数没有 benchmark 学术意义。

```bash
uv run dumemeval run --config examples/user_preference.yaml --mock --no-resume
```

这个例子展示两 session memory transfer。

## 真实数据

```bash
uv run dumemeval prepare --dataset locomo
uv run dumemeval run --config configs/backends/locomo_everos.yaml
```

真实执行需要可用 agent、memory 服务、Docker/Harbor（如配置使用 Harbor）和模型凭据。

## Agentic 环境

MemoryArena shopping 还需要 webshop server、商品库和 endpoint；YAML 的 `task.task_environment` 只声明并注入环境，不会自动启动外部服务。

```bash
uv run dumemeval prepare --dataset bundled_shopping
uv run dumemeval run --config configs/smoke/shopping_transfer.yaml --mock
```

## 结果

```text
TaskExecution → SampleResult/Verdict → BenchmarkResult → MetricReport → TaskResult
```

每个 task 写入 result.json/report.md，run 写入 summary.json/summary.md/index.json。
