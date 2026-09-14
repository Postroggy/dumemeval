# 内置 smoke 数据（官方数据集子集）

本目录是**官方数据集的精简子集**，随仓库分发，供 `configs/smoke/` 真跑对照零下载使用。
完整官方数据不随仓库分发，用 `dumemeval prepare` 下载到本地缓存（见 `docs/datasets/prepare.md`）。

| 文件 | 数据集 | 内容 | 许可 |
|---|---|---|---|
| `locomo_smoke.json` | LoCoMo（snap-research/locomo） | 对话 `conv-26` 的 `session_1..4` + evidence 落在其内的 5 题（5 类别 × 各 1 题，含 cat5 对抗题） | CC BY-NC 4.0 |
| `shopping_smoke.jsonl` | MemoryArena bundled_shopping（ZexueHe/memoryarena） | 第 0 个样本的前 2 回合（跨回合记忆约束） | 见 HF dataset 页 |

- 格式与官方完全一致，改动仅为「截断 / 取样」，未改写任何字段语义。
- **许可声明**：LoCoMo 以 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 发布。
  本目录是对其 `locomo10.json` 的 Adapted Material，按同一许可分发（非商业用途 + 署名）。
  MemoryArena 数据见 HF 仓库页许可。本项目的 Apache-2.0 不覆盖第三方数据。
- 这些子集用于**验证评测链路**（有记忆语义、能出官方口径 F1），不是论文数字。
  分数不可引用；完整数据才可引用。

重新生成（保持与 `dumemeval prepare` 输出一致）：

```bash
# locomo_smoke.json == prepare 的 slice_locomo_smoke(n_sessions=4, per_category=1)
# shopping_smoke.jsonl == prepare 的 slice_shopping_smoke(n_rounds=2)
```
