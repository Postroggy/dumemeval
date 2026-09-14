# 跨 run 比较（compare）

- 状态：implemented
- 源码：`src/dumemeval/comparison/service.py` · `src/dumemeval/comparison/report.py` · `src/dumemeval/models/run.py`
- CLI：`dumemeval compare`

## 问题

业务只问两件事：

1. 接了这个 memory 之后，agent 的完成质量/效率/速度有没有变化？
2. 同一个 agent 换不同 memory 系统，谁更好？

框架此前能跑出两份 `summary.json`，但**对比靠人肉**。

## 方案

一个命令覆盖两个场景，用 `--baseline` 区分：

```bash
dumemeval compare runs/base runs/mem --baseline runs/base   # 出 Δ 列
dumemeval compare runs/everos runs/mem0 runs/none           # 无 baseline → 出 best 列
```

纯函数：只读 `summary.json` + `experiment_config.json`，不触发执行。落在 `pipeline/report` 层，不碰主循环。

三条硬约束：

| 约束 | 实现 | 不这么做会怎样 |
|---|---|---|
| 方向性感知 | `MetricDirection`：`cost_usd` / `*_latency_ms` / `hallucination_rate` / `error_rate` / `tokens_*` 越低越好 | `cost +0.43` 会被渲染成绿色好消息 |
| 缺值不编造 | 某臂缺该指标 → `None`，`delta()` 返回 `None` | 用 0 填充会把「没测」伪装成「测得 0」 |
| 可比性警告 | benchmark / judge 模型 / task 数不一致、任一臂 mock → 进 `warnings`，mock 时整表标「不可引用」 | 业务拿着不可比的表做决策 |

另加：**重复 label 直接拒绝**——同一 run 传两次会产生同名列且 Δ 恒 0，是无意义输出。

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| `compare` + `leaderboard` 两个命令 | leaderboard 本质是「不指定 baseline 的 compare」，对齐与渲染逻辑要维护两份 |
| 一次 run 内同时跑 baseline + memory 两臂 | 主循环要引入「多臂」概念，破坏 `EvalTask` 语义单一性；两次 run + compare 更符合分层 |
| 在 `report.py` 里加比较逻辑 | 报告负责单 run 渲染；跨 run 是另一件事，混在一起会让 `report.py` 承担两个职责 |

## 语义边界

- 只对齐 **run 级**指标（`summary.metrics`），不做 per-task diff
- 准入只看 `summary.json` 是否存在（缺则报「先跑一次评测再 compare」）；`experiment_config.json` 可选，缺失/解析失败则 `provenance=None`。**run_id 不参与准入**——`RunProvenance.run_id` 只用于结果↔测试追溯（见 docs/architecture/run-artifacts.md）
- `memory.type: none` 不是强制 baseline：谁当基线由 `--baseline` 指定，none 只是普通一臂
- 没有统计显著性：单次 run 的差值可能来自采样噪声，多次 attempts 的 mean±std 尚未实现
- baseline 的选择由使用者负责；框架不校验「两臂是否真的只差一个变量」，只能检测已记录的 benchmark / judge / task 数

## 未完成

- `memory_conditioned_gain` 仍需手动跑两臂再 compare，未做成一条命令
- per-task 级 diff（定位是哪个样本变好/变差）
- 多次 attempts 的 mean ± std
