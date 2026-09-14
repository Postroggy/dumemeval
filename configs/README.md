# 配置与示例

数据分三层（详见 [docs/datasets/prepare.md](../docs/datasets/prepare.md)）：

| 目录 | 用途 | 数据 |
|---|---|---|
| [`examples/`](../examples/) | 零依赖：装完就能 mock | 仓库自带 `examples/data/locomo_mini.json`（占位对话，分数无学术意义） |
| [`configs/smoke/`](smoke/) | 默认真跑对照：官方子集 × transfer / test_only | `data.name` 解析（`locomo_smoke` / `shopping_smoke`，零下载） |
| [`configs/backends/`](backends/) | 换 memory 后端或跑全量 benchmark | `data.name` 解析（`locomo` / `bundled_shopping`，需 `dumemeval prepare`） |

内置数据用 `data.name` 逻辑名引用，框架按 仓库捆绑 → prepare 缓存 自动找文件，
配置里不出现任何路径。sessions 在 benchmark 路径下是占位，必须标
`placeholder: true`（真实 sessions 由适配器生成）。

```bash
make example      # examples/locomo_mini.yaml --mock
make prepare      # 下载完整官方数据到缓存（locomo + shopping）
make smoke-mock   # 四臂编排（数据零下载）
make smoke        # Harbor 真跑（需 ANTHROPIC_* + Docker；shopping 还需 webshop :8005）
```

单臂：

```bash
.venv/bin/python -m dumemeval run --config examples/locomo_mini.yaml --mock
.venv/bin/python -m dumemeval run --config configs/smoke/locomo_transfer.yaml --no-resume
.venv/bin/python -m dumemeval run --config configs/backends/locomo_everos.yaml
```

设计说明：[`docs/execution/smoke-matrix.md`](../docs/execution/smoke-matrix.md)。
