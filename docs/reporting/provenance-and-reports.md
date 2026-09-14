# 实验溯源与报告产出

- 状态：implemented
- 源码：`src/dumemeval/artifacts/provenance.py` · `src/dumemeval/artifacts/report.py` · `src/dumemeval/pipeline/`

## 问题

一份报告要能被引用，必须回答：**哪次代码、哪份配置、怎么重跑、是不是 mock**。此前报告只有指标数字，别人拿到无法复现，也分不清这是真跑还是占位。

## 方案

跑之前先落 `experiment_config.json`（脱敏配置 + git + 复现命令），跑完把同一份 provenance 注入 per-task 报告和整批 summary。

一次评测的产出：

| 文件 | 内容 |
|---|---|
| `experiment_config.json` | 脱敏配置（键名含 KEY/SECRET/TOKEN/PASSWORD/AUTH → `***`）+ git commit/branch/dirty + 复现命令 + judging 参数 |
| `<task>__<backend>/report.md` · `result.json` | 四维指标 + 官方口径 + Reproduce 块 + Errors 摘录 |
| `summary.md` · `summary.json` | pooled 官方口径 + `metrics`（run 级扁平指标，供 compare diff）+ 同上溯源 |
| `checkpoints/<task>.json` | task 级断点续跑（原子写盘） |

mock 时报告正文带横幅：**observation 是占位文本，指标仅验证编排，不可引用为实验结果**。

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 只在 CLI 打印溯源 | 报告被转发/存档后信息就丢了；溯源必须在产物里 |
| 报告里写完整配置（不脱敏） | 会把 API key 落盘进可能被分享的文件 |
| 跑完再采集 git | 跑的过程中若切分支，记录的就是错的 commit |

## 语义边界

- `git.dirty=true` 意味着工作区有未提交改动——commit 号不足以还原当时代码
- 尚未计量的项保持缺省/0，不假装有值：judge token、ANSWER context tokens、Add/Search 延迟 P50/P95
- Quality 的 `precision` 是「含任一 GT fact 的 memory 文件占比」（文件级命中），不是逐条标注的 precision；报告里已标注该近似

## 未完成

- judge 调用的 token/cost 未计量（目前只有 Harbor trial 的 agent token）
- 检索上下文长度（对比横评常用的效率轴）未采集
- Add/Search 延迟只有均值，无 P50/P95
