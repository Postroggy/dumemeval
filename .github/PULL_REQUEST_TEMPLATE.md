<!-- 任何 PR 都要有设计文档，无例外。见 CONTRIBUTING.md「PR 流程」 -->

## 设计文档

`docs/<模块>/<功能>.md`（必填，贴链接）：

<!-- 例：docs/adapters/mem0.md -->

## 关联 Issue

Fixes / Closes #<issue 号>（没有对应 Issue 的先开一个再提 PR；纯文档小改可写「无」）：

## 改动类型

- [ ] 新功能 / 新扩展点实现
- [ ] 修 bug
- [ ] 重构（行为不变）
- [ ] 配置 / CI / 工程
- [ ] 只改文档

## 这个 PR 解决什么

<!-- 一段话。不要复述 diff -->

## 检查单

- [ ] 设计文档已写，且与实现一致（提 PR 前 double check 过）
- [ ] 文档含「备选方案与否决理由」（新功能 / 重构必填）
- [ ] 未改禁区文件：`lifecycle/runner.py`（`SessionRunner` / `ParallelTaskRunner` 主循环）、`metrics` 的分支计算逻辑等（必须改时，先在本 PR 说明理由并 @维护者）
- [ ] 新公共类型是 pydantic `BaseModel`
- [ ] 数据集 PR：适配器 docstring 有 `Source:` URL，`docs/datasets/README.md` 表格已更新
- [ ] `make ci` 绿（与 GitHub Actions 同口径：ruff + mypy + pytest + build + mock smoke）
- [ ] 若改了指标语义：在 `GOVERNANCE.md`「勿过度解读」补一句

## 语义边界（如引入新指标 / 改判分）

<!-- 这个改动测不出什么？哪些数字不能过度解读？「未测」和「测得 0」是否可区分？ -->
