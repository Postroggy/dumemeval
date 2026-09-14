---
name: Memory backend
about: 新增一个 memory 后端 adapter（产品 API 或目录型）
labels: extension, adapter
title: "[adapter] 新增 memory 后端："
---

## 目标

接入哪个 memory 系统？官方文档 / API 链接：

## 实现约定（对照 GOVERNANCE.md）

- [ ] **设计文档先行**：`docs/adapters/<name>.md`（生命周期如何映射到该产品 + 备选方案）
- [ ] 新文件 `src/dumemeval/adapters/<name>.py`，子类 `BaseMemoryAdapter`
- [ ] `inject` 写了注入通道（`declare_mount` 或 `agent_env`）——`tests/test_adapter_contract.py` 绿
- [ ] `register_adapter`（或写入 `_ADAPTER_REGISTRY`）
- [ ] **没有**改 `SessionRunner` / `ParallelTaskRunner` 主循环
- [ ] **没有**在其他模块加 `if type == "<name>"`
- [ ] 测试覆盖 setup 清空、inject、snapshot、至少一种错误路径

## 生命周期语义

说明 `setup / inject / snapshot / observe / seed_history` 如何映射到该产品 API。
若产品没有清空接口，如何隔离（user_id / project_id）？
