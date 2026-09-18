# MemoryArena 配置入口

设计见[接入说明](../../docs/datasets/memoryarena/README.md)，安装、资源准备、运行和排错统一见
[运行指南](../../docs/datasets/memoryarena/clean-setup.md)，结果与限制见[验收报告](../../docs/datasets/memoryarena/acceptance.md)。

| 配置 | 用途 |
| --- | --- |
| `shopping.yaml` / `travel.yaml` / `search.yaml` / `math.yaml` / `phys.yaml` | 五场景统一 `dumemeval prepare` / `dumemeval run` 入口，每个默认选择一条完整数据。 |
| `search-bm25.yaml` | 官方 BM25 选项，使用固定本地索引，不需要 embedding 端点。 |
| `controlled-math.yaml` | Claude Code 的完整两轮 Math on/off，相同提示与镜像内共用 Skill。 |
| `controlled-math-hermes.yaml` | 相同 Math 样本的 Hermes 对照；通过 `hermes_repro.py` 处理指定 Harbor 版本的兼容。 |
| `hermes-memory-link.yaml` | 可选随机标记记忆通道诊断，非官方样本/分数。 |

早期本机代理通信与合成持久化调试配置已移出交付目录；正式复现使用上表的场景与对照配置。
历史运行所用代理的版本和启动方式保留在运行指南与原始证据中，用于复核当时的实验环境。

通用场景模板需导出 `MEMORYARENA_AGENT_MODEL`、`MEMORYARENA_JUDGE_MODEL`、`ANTHROPIC_AUTH_TOKEN`、
`ANTHROPIC_BASE_URL`；外部资源与 worker 的变量按运行指南设置。
通用 on/off 会改变记忆提示后缀，严格同提示对照使用 `controlled-math*.yaml`。
Travel 的默认流程按官方六槽位报告 PS/SPS/SR；on 用目录记忆和 `memory_session_transfer`，
off 用 `test_only`，环境仍提供累计计划与反馈。Shopping 通过固定上游 `compute_reward.py` 报告
完整 reward；`MEMORYARENA_SHOPPING_ATTRIBUTE_MODE=auto|llm|string` 控制属性判定，默认 `auto`
在 worker 有 OpenAI/Azure 凭据时用 LLM，否则按官方字符串回退。模型可用
`MEMORYARENA_SHOPPING_ATTRIBUTE_MODEL` 指定，默认 `gpt-4o`。
新实验使用新输出目录，`--no-resume` 不会移除评分检查点；缺失证据或跳过评分保持未测。
