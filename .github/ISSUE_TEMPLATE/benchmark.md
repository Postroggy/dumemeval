---
name: Benchmark dataset
about: 新增一个官方数据集适配（build_tasks + 官方口径计算器）
labels: extension, benchmark
title: "[benchmark] 新增数据集："
---

## 目标

数据集名称、**官方仓库 / HF dataset URL**、论文链接、主指标名称：

## 实现约定

- [ ] **设计文档先行**：`docs/datasets/<dataset>.md`，并在 `docs/datasets/README.md` 表格追加一行
- [ ] 适配器 docstring 带 `Source:` 官方仓库/HF URL（本地 `Dataset/` 路径不算来源），有论文加 `Paper:`
- [ ] `datasets/benchmarks/<name>.py`：`build_tasks` → `EvalTask`，问答 session 填 `SessionSpec.query`
- [ ] `metrics/<name>.py`：`MetricCalculator`，docstring 标注官方实现文件名 + 关键函数
- [ ] `register_benchmark` + `register_calculator`（不必改 factory 的 if/elif——已经没有）
- [ ] **没有**新增 `scripts/<bench>/ingestion.py` 六段流水线
- [ ] 官方口径测试（用固定 fixture，不要打真实 LLM）

## 口径对齐

贴官方评测脚本路径 + 我们镜像的函数名。若官方代码未发布，在 calculator docstring 写「自定义，非官方镜像」。
