---
name: Bug report
about: 报告 bug：跑不起来 / 结果异常 / 行为不符合预期
labels: bug
title: "[bug] "
---

请附上运行命令、Python 版本、配置文件和关键错误日志。mock 不需要 Docker/Harbor/key；真实 Harbor 运行才需要这些依赖。

## 环境

- dumemeval 版本（`pyproject.toml` version 或 commit）：
- 运行模式：mock / Harbor 真跑
- 运行命令与关键日志：
- Python 版本：

## 复现步骤

```bash
# 最小复现命令（优先用自带数据：examples/locomo_mini.yaml）
```

## 期望 vs 实际

期望行为：

实际行为（附关键日志 / report.md 片段）：

## 补充

- 涉及哪个扩展点（adapter / protocol / benchmark / calculator / task_environment）？
- 是否能确定与 memory 注入有关？（`result.json` 的 `memory_ops` 里 inject 是否 skip）
