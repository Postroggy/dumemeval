# 默认 real smoke 配置

- 状态：implemented
- 源码：无（纯配置）；数据捆绑在仓库 `data/smoke/`（官方子集，零下载）
- 配置：`configs/smoke/`

## 测什么

最小对照矩阵：**同一份有记忆语义的官方子集 × 接了 memory vs 没接**。
分数用来验证「真跑链路能出官方口径」，不是论文数字。

| 臂 | 配置 | 数据 | memory | 协议 |
|---|---|---|---|---|
| A | `locomo_transfer.yaml` | `data.name: locomo_smoke`（4 session / 5 题） | directory | `memory_session_transfer` + `proactive` |
| B | `locomo_test_only.yaml` | 同上 | directory（生命周期关闭） | `test_only` |
| C | `shopping_transfer.yaml` | `data.name: shopping_smoke`（第 0 样本前 2 回合） | directory | `memory_session_transfer` + `proactive` |
| D | `shopping_test_only.yaml` | 同上 | directory（生命周期关闭） | `test_only` |

四臂 memory 均为 `type: directory`（同一 adapter），runtime 均为 claude-code；
同数据、同 agent、同 judge，唯一自变量是协议。shopping 两臂额外带
`task_environment: {type: webshop}`（框架内置 provider），`base_url` 默认
`${WEBSHOP_ENV_URL:-http://127.0.0.1:8005}`；memory 后端的横评（EverOS /
hermes_builtin / directory）在 `configs/backends/` 用完整数据。

数据用 `data.name` 逻辑名引用（框架解析 仓库捆绑 → 缓存，见
[docs/datasets/README.md](../datasets/README.md)）。sessions 均为占位
（`placeholder: true`），真实 sessions 由适配器生成。

不要用 `examples/data/locomo_mini.json` 做真跑——那是手写示例（约 1.6K 字符、
2 个 session），不是官方 conv-26 子集，没有 evidence 锚定的记忆语义。
捆绑子集只验证链路，分数不可引用（来源与许可见 `data/smoke/README.md`）。

## 怎么跑

```bash
# 编排（无 Docker / 无密钥；数据零下载）。`make ci` 含这一步
make smoke-mock

# 真跑（需 Harbor extra + Docker + ANTHROPIC_*；runtime 用 claude-code，需 dumeval-claude-code:latest）
uv sync --extra dev --extra harbor --extra judge
make smoke          # 四臂串行；单臂失败不阻断其余
dumemeval compare results/smoke/locomo_test_only results/smoke/locomo_transfer \
  --baseline results/smoke/locomo_test_only
```

完整数据（`configs/backends/` 全量实验）用 `dumemeval prepare` 下载到缓存，
见 [docs/datasets/prepare.md](../datasets/prepare.md)。

## 体量

- locomo：9 次 agent 调用 / 臂（4 个 ingest session + 5 道 QA session），对话约 1.2 万字符
- shopping：2 次调用 / 臂（2 回合）；历史同规模约 31 万 input token（环境交互放大）

## 未完成

- Harbor 0.22 的 hermes adapter 在 install 末尾执行非法子命令 `hermes version`
  （CLI 只有 `hermes --version`），hermes runtime 臂被挡住；smoke 四臂默认走
  claude-code runtime（memory 仍是 directory）
- shopping 官方分需要 MemoryArena webshop env server（`WEBSHOP_ENV_URL`，默认
  http://127.0.0.1:8005）。shopping 臂的 `task_environment: webshop` 已指向该
  地址；未启动时 agent 无法 `click[Buy Now]`，ASIN exact match 会是 0——这是
  环境缺口，不是样本量问题。商品库见官方 `setup_web_shopping.md`
