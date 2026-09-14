# 模块划分清理：闭合 metrics 禁区、去空壳、统一数据层命名

- 状态：implemented
- 源码：`models/` · `metrics/` · `execution/executor.py` · `datasets/loader.py` · `cli/` · `pipeline/`
- 关联：本篇是一次结构重构，行为不变

## 问题

演化留下 4 处结构债，社区看到会困惑「该用哪个」：

1. **`metrics` 运行时 import `execution`**（破禁区）：`metrics/utility.py` 与 `metrics/efficiency.py` 直接 `from ..execution.executor import SessionOutcome`。`GOVERNANCE.md` 规定 metrics 只吃 `EvalResult` / `EvalTask`，保持纯计算。
2. **两个空壳包**：`utility/metrics.py`（8 行）、`efficiency/metrics.py`（8 行）只做再导出，**无任何代码 import**（仅自身），是死代码。
3. **`dataloader/` 与 `datasets/` 命名撞车**：职责其实清晰（前者「从哪读」，后者「怎么变成 EvalTask」），但名字看不出区别，加数据集时容易走错目录。
4. **两个文件到拆分线**：`cli.py` 328 行（5 个子命令解析+执行混在一起：run / doctor / list / compare / prepare）、`pipeline.py` 315 行（per-task 指标 + pooled 聚合 + run 级 metrics + summary 落盘）。

## 方案

### 1. `SessionOutcome` 归位 `models/`

`SessionOutcome` 是纯 pydantic 结果模型（session_id / success / observation / tokens），本该和 `EvalResult` 同层。搬到 `models/`，`execution/executor.py` 再导出保持既有 import 路径可用。

闭合后：`metrics` 只依赖 `models`，禁区从「基本守住」变成「真的守住」。

### 2. 删空壳，`QualityProbe` 归位

- 删 `utility/` `efficiency/` 两个包（无人 import）
- `quality/metrics.py` 里的 `QualityProbe` 不是指标计算器（它扫 session jsonl 提取 memory 事件），移到 `metrics/probe.py`，删掉 `quality/` 包

### 3. `dataloader/` → `datasets/loader.py`

数据加载和数据集适配都属于「数据」这一层，合并到 `datasets/`：

```
datasets/
├── loader.py      # 从哪读（local / hf / git + 版本锁定）
├── benchmark.py   # 怎么变成 EvalTask（BenchmarkAdapter 协议）
└── benchmarks/    # 各数据集实现
```

### 4. 拆 `cli` 与 `pipeline`

| 原 | 拆成 |
|---|---|
| `cli.py`（328） | `cli/__init__.py`（parser 组装）+ `cli/run.py` + `cli/inspect.py`（doctor/list）+ `cli/compare.py` + `cli/prepare.py` |
| `pipeline.py`（315） | `pipeline/__init__.py`（finalize_run 编排）+ `pipeline/metrics_run.py`（per-task + pooled + run 级）+ `pipeline/summary.py`（落盘） |

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| `SessionOutcome` 留在 execution，metrics 改用 duck typing（`getattr`） | 放弃类型检查换取「不动结构」，mypy --strict 下反而更脆 |
| 保留 `utility/` `efficiency/` 空壳做向后兼容 | 尚未发布，无外部使用者；留着只会让社区困惑「两个 utility 用哪个」 |
| `dataloader/` 改名为 `sources/` 而非并入 `datasets/` | 仍是两个顶层包，社区第一次找还是要猜；并入后「数据的事都在 datasets/」更好记 |
| 不拆 `cli.py` / `pipeline.py`（300 行是软信号） | 已到线且都在承担多个子职责；社区改 compare 时不该被迫读 run 的全部逻辑 |
| 用 `git mv` 保留历史但不改 import | import 路径不改等于没解决「走错目录」问题 |

## 影响面

- 删除：`utility/` `efficiency/` `quality/` `dataloader/` 四个包
- 新增：`metrics/probe.py`、`datasets/loader.py`、`cli/` 包、`pipeline/` 包
- 修改：`models/`（收 `SessionOutcome`）、`metrics/utility.py` `metrics/efficiency.py` `metrics/base.py`（改 import）、测试 import 路径
- **行为不变**：无指标语义改动，无 CLI 接口改动

## 语义边界

纯结构重构。任何指标数值、报告字段、CLI 参数均不变——用现有 396 个测试作为回归基线（改完必须仍全绿，且不是靠改断言换绿）。

## 未完成

- `models/__init__.py` 273 行，收了 `SessionOutcome` 后接近 300：后续可按「task 级结果 / run 级结果」再拆
- `adapters/hermes_builtin.py` 300 行，未在本次处理
