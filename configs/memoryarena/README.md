# MemoryArena 本地运行说明

五个场景配置都通过常规 `dumemeval run` 入口使用已注册的受管环境和 Harbor，
每个配置选取一条完整源数据。独立的 `cliproxyapi-smoke.yaml` 已通过
GPT-5.5 medium 的真实两问题 Math 诊断，设置和证据见
[CLIProxyAPI 联调说明](../../docs/datasets/memoryarena-cliproxyapi.md)。
`cliproxyapi-memory-smoke.yaml` 提供独立的合成文件持久化探针。
完整两轮 `controlled-math.yaml` 对照实验及依赖外部资源的官方工具通信检查也已通过，
见 [本地验收记录](../../docs/datasets/memoryarena-acceptance.md)。

Hermes 0.21.3 的同样本真实 on/off 复跑和随机标记记忆诊断也已通过。
配置、兼容入口、固定镜像构建和脱敏证据见
[Hermes 验收与复现](../../docs/datasets/memoryarena-hermes.md)。

## 安装与准备

新环境先阅读 [从零安装指南](../../docs/datasets/memoryarena-clean-setup.md)，
其中包含完整 Windows 步骤：代理登录、固定版本 Agent 镜像和隔离依赖环境，
不依赖作者机器上的私有安装。

在 DuMemEval 根目录中，使用 Python 3.12 和 uv 执行：

    uv sync --extra dev --extra harbor --extra judge --extra memoryarena --locked

memoryarena 可选依赖组将 Anthropic 限定为 <1，因为固定版本的上游后端传入了
Anthropic 1.x 已移除的 temperature。其他场景依赖按需安装在专用上游 worker 环境中。

导出 MEMORYARENA_AGENT_MODEL、MEMORYARENA_JUDGE_MODEL、ANTHROPIC_AUTH_TOKEN 和
ANTHROPIC_BASE_URL。模型 ID 必须由对应端点支持，凭据放在环境变量中。
两组的 MEMORYARENA_AGENT_VERSION 默认均为 2.1.89。
Agent 使用 Claude Code 默认采样；Harbor 适配器未为该 Agent 暴露 temperature 设置。

    uv run dumemeval prepare --environment-config configs/memoryarena/math.yaml --clone-reference

如果官方源码不存在，该命令会克隆到 `.cache/memoryarena`，检出
`6cd9de14b71915e39ac742a20dc33785e14b6aab`，核验受版本控制的源码、依赖和资源路径，
并写入 preparation.json。prepare 成功不代表 Docker 或模型已就绪。
重复执行会核验现有检出目录；源码有未提交修改或版本不符时失败。

MEMORYARENA_REFERENCE 可指定已有的固定版本检出目录。
MEMORYARENA_PYTHON 可指定另一个 worker Python 可执行文件。
DuMemEval 保持 Python 3.12，独立启动脚本允许使用与上游兼容的较旧 worker Python。

| 场景 | 额外准备 |
| --- | --- |
| Math / Phys | 无需语料或商品资源。除 memoryarena 依赖组外，安装所选 backend 的 SDK：OpenAI/OpenRouter 用 openai（包含于 judge 依赖组），Anthropic 用 anthropic，Gemini/Google 用 google-genai。prepare 会检查实际 worker 中的依赖。 |
| Travel | 准备官方 travel_planner_env/database CSV，其中 flights/clean_Flights_2022.csv 按固定版本的 [数据库 README](https://github.com/ZexueHe/MemoryArena/blob/6cd9de14b71915e39ac742a20dc33785e14b6aab/env/env_systems/travel_planner_env/database/README.md) 单独下载。MEMORYARENA_TRAVEL_DATABASE 可覆盖数据库目录。 |
| Shopping | 使用已验证的 worker-requirements.txt、Python 3.10.21 和 Java 17，并设置 MEMORYARENA_JAVA_HOME。官方依赖锁定存在冲突，兼容 worker 清单是已记录的差异。将 [商品数据库](https://huggingface.co/datasets/ai-hyz/MemoryArena-product-db) 下载到 MEMORYARENA_PRODUCT_DATA（默认 .cache/memoryarena-products）。必需文件：items_shuffle.json、items_ins_v2.json、domain_data.json、product_catalog/*.json 和 search_engine/indexes-full/*。 |
| Search | 按固定版本的 [索引准备指南](https://github.com/ZexueHe/MemoryArena/blob/6cd9de14b71915e39ac742a20dc33785e14b6aab/setup_web_search_env.md) 操作。提供匹配的 MEMORYARENA_SEARCH_INDEX、MEMORYARENA_SEARCH_IDS 和 MEMORYARENA_SEARCH_CORPUS 文件。OpenAI searcher 还需要与索引匹配的 OPENAI_API_KEY、OPENAI_BASE_URL 和 MEMORYARENA_EMBEDDING_MODEL。上游导入依赖 FAISS、FastMCP、transformers、Torch 和 Tevatron。 |

安装后，用对应场景 YAML 执行 prepare。缺少文件或模块时返回非零退出码。
运行时也会记录外部资源 SHA-256，请保留下载版本和准备清单。
Search 上游 tokenizer 加载 Qwen/Qwen3-0.6B 时没有 revision 参数：
prepare_assets.py 会固定缓存，准备阶段校验版本和离线标志。
search-bm25.yaml 是已经验证的官方 BM25 选项，不需要 embedding 端点。
目前未实现或报告 qrel recall。

## 运行 on/off 两组

如需复现已验证、提示词完全相同的对照实验，使用 controlled-math.yaml 并按
[验收指南](../../docs/datasets/memoryarena-acceptance.md) 操作。
下方通用示例还会改变记忆指令后缀，因此改变的实验因素更多。

Docker 必须运行。框架管理的官方服务在临时端口启动，结束后自动清理，
无需手动启动 MemoryArena 服务。
Docker Desktop 内的 Agent 使用 host.docker.internal；原生 Linux 需在
task.task_environment.config.agent_host 中指定可达的宿主地址并配置相应路由。
上游控制服务只监听宿主回环地址。

PowerShell 示例（需已导出实际模型 ID 和凭据）：

    $env:MEMORYARENA_ARM = 'on'
    $env:MEMORYARENA_PROTOCOL = 'memory_session_transfer'
    $env:MEMORYARENA_MEMORY_TYPE = 'directory'
    uv run dumemeval run --config configs/memoryarena/math.yaml --no-resume

    $env:MEMORYARENA_ARM = 'off'
    $env:MEMORYARENA_PROTOCOL = 'test_only'
    $env:MEMORYARENA_MEMORY_TYPE = 'none'
    uv run dumemeval run --config configs/memoryarena/math.yaml --no-resume

    uv run dumemeval compare results/memoryarena/math/off results/memoryarena/math/on --baseline off --output results/memoryarena/math/comparison

将 math 替换为 phys、travel、search 或 shopping 即可选择其他场景。
重复实验使用不同输出目录。目录适配器在 setup 时清空本次实验记忆；
复用已成功的检查点时跳过 setup。传递用临时目录按执行尝试隔离，
避免失败运行的内容进入新的尝试。

官方评分检查点保存在运行目录的 `scoring/` 下。
证据、judge/数据配置和评分源码相同时，复用已完成结果。
遇到未完成或损坏的评分尝试会停止，不会自动再次调用 judge。
先检查该尝试，再决定是否使用新输出目录重新运行。
`--no-resume` 控制执行结果复用；新实验及主动重新评分都应使用新运行目录。
挂载工具客户端在送达状态不明后也会保留待处理请求 ID，此时重试相同命令即可。
可使用 `--request-id ID` 在重试之间显式标识同一个逻辑动作。
JSON 类型参与请求身份比较。框架 judge 和官方 Math/Phys worker 的 SDK 重试均已关闭；
框架只对已收到的 429 拒绝进行重试。超时、连接和服务端错误保留为未测。
外部代理按从零安装指南关闭自动重发和切换凭据重试。

两组均设置 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1。Harbor 0.22 在每个全新 trial 容器中
将实际 CLAUDE_CONFIG_DIR 设为 /logs/agent/sessions。
[原生记忆设置](https://code.claude.com/docs/en/memory) 关闭自动记忆，
on 组的目录记忆仍作为显式存储。最小真实运行已核验 Claude 进程环境中的该标志。
环境/工具指令相同；此通用示例改变记忆可用性及其提示词后缀。
Travel 的隔离会话基线与上游无记忆 Agent 累积历史的行为不同。

配置使用 subset: 1，只选择一个任务。诊断配置可额外设置 max_questions: 2，
但截断任务不能声称取得完整 paper 或 bundle 的成功率。

## 产物与边界

- `experiment_config.json`：脱敏配置、git/源码/配置指纹、依赖、复现命令和实际运行时指纹。
- `environments/<task>/{preparation.json,runtime.json,trace.json,service.log}`：
  资源哈希、服务状态、任务/会话/动作证据、工具和原始评分记录。
- `trials/<task-session>/agent/trajectory.json`：真实 Harbor 运行时的 Agent/代码/工具轨迹；
  收集报告前清除已知凭据。
- 原有 memory/transfer、snapshots、任务 result.json/report.md 和运行
  summary.json/summary.md 继续由正常流水线输出。
- 比较报告会警告控制变量缺失/变化以及执行不完整。
  未测证据与实际评判错误所得的 0 分分开表示。

一个环境对应一个任务，一份工具访问权限对应一个会话。
Agent 不能重置/关闭服务或选择评分参考答案。重复投递 ID 返回缓存结果。
结果不明的写操作不会再次执行；需要重新实验时使用新运行目录。
取消时先等待自有服务启动过程结束，再清理。

Shopping 上游启动器以系统时间为随机种子初始化。
运行时 provenance 记录这一点，比较报告警告 reset seed 等价性未经验证。
不能声称配置中的 seed 控制了该初始化。

## 本地检查

    uv run pytest tests/test_memoryarena_contracts.py tests/test_memoryarena_client.py tests/test_memoryarena_cli.py tests/test_memoryarena_official_parity.py tests/test_memoryarena_runtime.py tests/test_memoryarena_completion.py

进行官方评分比较和 HTTP 集成测试前，将 MEMORYARENA_REFERENCE 指向固定版本的检出目录。
CLI 测试使用自编固定样例和显式 mock 执行；一致性测试在固定输入上运行官方函数。
HTTP 测试启动真实 Math/Phys 服务，通过真实 socket 调用挂载工具脚本，
judge 使用确定性的本地固定样例。这些测试均不等同于真实 Harbor/LLM 实验。
缺少依赖或官方源码时，可选检查会明确跳过。
验收状态见校验清单和 [接入设计](../../docs/datasets/memoryarena.md)。
