# Utility 接官方口径：task_success 的来源

- 状态：implemented
- 源码：`src/dumemeval/metrics/dimensions/utility.py` · `src/dumemeval/pipeline/metrics_run.py` · `src/dumemeval/pipeline/__init__.py`
- 关联：`docs/reporting/compare.md`（跨 run 比较）

## 问题

`utility.success_rate` 的语义是「session 跑完且采集到输出」（完成率），但 `utility.task_success` 也从同一来源推导——**报告里 Utility 段回答不了「任务做对了吗」**。任务对错明明已经算出来了：benchmark 官方口径（LoCoMo F1、shopping ASIN match 等）挂在 Benchmark 维度，却没有回填 Utility。

agent-first 的核心问题「memory 让 agent 做得更好吗」要求 Utility 段反映任务结果，不是运行状态。

## 方案

benchmark 计算出主指标（`f1` / `accuracy` / `overall_success` / `solving_rate` 等第一个命中项）后，回填：

```python
ur.task_success = official_score >= 0.5
ur.details.append({"source": "benchmark_official", "score": ..., "threshold": 0.5})
```

- 顺序调整：benchmark bundle 先算（只依赖 task/result），`task_metrics` 接收 `official_score` 再跑 Utility——保证 `result.metrics` 的扁平值不出现新旧两套
- 无 benchmark 时保持原语义（全部 session 成功 = task_success），并在 details 无 official 来源时可知
- `success_rate` 不动：它继续表示完成率；两者语义分离并在 GOVERNANCE「勿过度解读」写明

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| success_rate 也用官方分 | 完成率与正确率是两个量：3 题对 1 题，完成率 1.0、正确率 0.33；合并会丢信息 |
| UtilityCalculator 内部反查 result.benchmark | 计算器之间互相依赖，顺序耦合；经 `MetricInput.extra` 显式传参更薄 |
| 新增第五个维度放官方分 | 官方口径已有 Benchmark 维度；这里只是把「任务结果」回填进 Utility 的 task_success，不新增维度 |
| 阈值 0.5 可配置 | 各官方口径的「及格线」语义不同（F1 0.5 vs ASIN 全对），写死 0.5 并在 details 里暴露 score 本身，让使用者自行解读 |

## 语义边界

- **多题 task 的 task_success 是 pooled 主分 ≥ 0.5**——「整体过半」不等于「每题都对」；逐题结果在 benchmark details
- 无官方口径的自定义任务（如 user_preference_memory）task_success 仍是完成率语义
- `memory_conditioned_gain` 依旧需要 compare 两臂，本改动不覆盖

## 验证

- `tests/test_utility_official.py`：official=1.0 → True；0.0 → False；None → 完成率回退；details 记录来源
- `tests/test_parallel.py` 的 finalize 集成测试继续绿（locomo pooled f1=0.5 → task_success True，阈值语义）
