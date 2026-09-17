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
| `cliproxyapi-smoke.yaml` / `cliproxyapi-memory-smoke.yaml` | 早期模型通信/合成持久化诊断，正式验收使用完整样本的 controlled 配置。 |

通用场景模板需导出 `MEMORYARENA_AGENT_MODEL`、`MEMORYARENA_JUDGE_MODEL`、`ANTHROPIC_AUTH_TOKEN`、
`ANTHROPIC_BASE_URL`；外部资源与 worker 的变量按运行指南设置。
通用 on/off 会改变记忆提示后缀，严格同提示对照使用 `controlled-math*.yaml`。
新实验使用新输出目录，`--no-resume` 不会移除评分检查点；缺失证据或跳过评分保持未测。
