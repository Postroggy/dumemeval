---
name: Eval protocol
about: 新增或补全一种评测协议（跨 session 生命周期语义）
labels: extension, protocol
title: "[protocol] 新增评测协议："
---

## 目标

协议名、要回答的评测问题（例如「有记忆 vs 无记忆」「训练后备份再测」）：

## 实现约定

- [ ] **设计文档先行**：`docs/lifecycle/<protocol>.md`（生命周期开关语义 + 备选方案）
- [ ] `EvalProtocol` 子类：`validate` + `should_inject_memory` 等开关
- [ ] `register_protocol`
- [ ] 若需要 runner 里尚不存在的动作（backup/restore），先在本 Issue 讨论钩子，**不要**直接改 `SessionRunner.run` 堆步骤
- [ ] 配置交叉校验：协议与 session 数 / `memory_inject` 不相容时要在加载配置时失败

## 现状

`memory_train_backup_test` 已注册但 **experimental**（行为等同 `memory_session_transfer`）。若你要做的是补全它，请直接认领并描述 backup/restore 的存储位置与隔离键。
