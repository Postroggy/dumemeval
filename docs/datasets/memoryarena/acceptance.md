# MemoryArena Issue #4：本地验收记录

本文保留初版实现的有限范围验证：用一条完整的两轮 Math 数据进行真实对照实验，
用真实官方工具验证依赖外部资源的场景，并对五个评分器进行固定输入的一致性比较。
这些记录不代表完整数据集评测，也不能证明记忆带来了统计显著的提升。
机器可读校验结果和筛选后的脱敏产物随本文提供，历史诊断单独保留。

后续独立审查发现 Search 评分单位和截断处理、客户端重试身份、评分恢复以及 mock CLI
固定样例存在缺陷。这些问题已修复并通过独立复验，见 [验收问题修复](acceptance-fixes.md)。
下方历史真实实验不能作为实验结束后所改代码的执行证据。

| 对照组 | 成功的 Harbor 会话 | 官方 paper pass rate | 记忆证据 |
| --- | --- | --- | --- |
| Off（关闭记忆） | 2/2 | 1.0 | 没有记忆挂载；原生自动记忆关闭 |
| On（开启记忆） | 2/2 | 1.0 | 首轮写入，第二轮读取并更新 |

官方分差为 **0**。记录的九个控制变量指纹，以及两份生成的任务指令均一致，比较报告无警告。
on 组记录了两次文件变化和一次成功读取。四个不同的原生会话 ID 证明会话彼此隔离。
Token/cost 字段是框架对用量的估算，不能当作代理账单或官方评测分数。

- [机器可读验收清单](acceptance-verification.json)
- [脱敏证据包](evidence.zip)：包含两组运行的 JSON/Markdown 对比、
  原生/ATIF/环境轨迹和记忆快照

实验结束后，曾收紧 Search snippet-limit 的类型校验并调整一处 CLI 字符串格式。
这两个文件的执行时版本均已归档，替换回它们即可重建记录中的实验代码指纹。
这是当时的验证边界。之后的验收修复改变了工具投递和评分行为，有单独的回归证据。

## 已接入的能力

数据集、记忆、执行器和评分器继续使用已有注册扩展点。
任务级环境适配器管理官方服务，执行器装饰器向 Harbor 提供工具。
Shopping、Travel、Search 及 Math/Phys 共用实现保留各自的交互和评分语义。
本次未新增 Agent、记忆后端或通用运行时插件系统。

目录适配器会记录文件变化和成功的 ATIF 结构化读取。
每次文件变化算作一个已观测写入事件；对同一文件的多次写入可能合并成一个事件。
任意 shell 读取、写入后恢复原内容等操作可能无法观测。
因此计数是下界，无法测量的值保留为 null/n/a。
Runner 仅通过可选的适配器钩子传递已完成的执行结果。

## 复现对照实验

按 [从零安装与完整运行步骤](clean-setup.md) 操作，
其中包含全新环境、固定版本下载、运行者登录认证、镜像构建、官方源码准备和两组 CLI 命令。

样本选择是确定性的：从完整 Math 数据行中选择问题最少、但至少有两个问题的一行，
数量相同则取最小 ID。锁定版本的数据选中 ID 39、paper `2507.18621`，共两个问题。
JSON 的 SHA-256 为
`82a430425b49471c68a8fc8a00caffe4fd505678fb8001f785abd565a5c3b868`。
选择过程不依据答案或模型表现。

两组均使用 `memory_instruction: none`、相同任务/环境指令、
镜像内同一份按记忆可用性生效的 Skill，并关闭 Claude 自动记忆。
共用 Skill 的 SHA-256 为
`6f89f70212ca90a88d70c5fc997a2b226823eb722908bd6721423e01f66a520e`。
记录实际构建的镜像 ID，两组之间保持不变。YAML 中使用镜像 tag，
因为 Harbor 会把它写入 Dockerfile 的 FROM 指令。重新构建的镜像 ID 不必等于历史值。

两组只改变记忆挂载、记忆可用性变量和传递策略，均使用 Claude Code 的默认采样行为。
不声称模型服务提供了全局确定性的随机种子。本实验验证执行和测量链路。

<a id="optional-worker-and-external-assets"></a>

## 可选 worker 与外部资源

已测试的 worker 使用 Python 3.10.21、Java 17、CPU Torch 2.2.2、
spaCy 3.7.5 及 `en_core_web_lg` 3.7.1、Pyserini 0.17.0、Transformers 4.51.3。
准确版本见 `configs/memoryarena/worker-requirements.txt`，全部安装在核心框架之外的独立环境中。
Shopping 官方依赖同时固定 spaCy 3.3.0 和 Pydantic 2.5.3，两者无法共同解析；
这里使用的兼容 worker 锁定清单是明确记录的依赖差异，未修改官方源码。

```powershell
$assetsRoot = Join-Path (Get-Location) '.cache\memoryarena-assets'
uv python install 3.10.21
uv venv --python 3.10.21 (Join-Path $assetsRoot 'worker')
$worker = Join-Path $assetsRoot 'worker\Scripts\python.exe'
uv pip install --python $worker --index-url https://download.pytorch.org/whl/cpu 'torch==2.2.2+cpu'
uv pip install --python $worker --no-deps -r configs/memoryarena/worker-requirements.txt
uv pip check --python $worker
$env:MEMORYARENA_PYTHON = $worker
# 先安装 Java 17，再指定实际安装目录。
$env:MEMORYARENA_JAVA_HOME = $env:JAVA_HOME
if (-not $env:MEMORYARENA_JAVA_HOME) { throw 'Set JAVA_HOME to the installed Java 17 directory' }
```

锁定清单中仅限 Windows 的依赖带有平台标记。
不声称已完成原生 Linux 宿主验证；Linux 需要相应调整路径和 Docker 宿主路由。

资源下载到显式指定的输出目录，不纳入源码版本控制。
准备命令包含固定的源码/数据/tokenizer 版本，并生成清单：

```powershell
uv run python configs/memoryarena/prepare_assets.py --scene travel --reference $env:MEMORYARENA_REFERENCE --output $assetsRoot
$env:MEMORYARENA_TRAVEL_DATABASE = Join-Path $assetsRoot 'travel\database'

uv run python configs/memoryarena/prepare_assets.py --scene shopping --output $assetsRoot
$env:MEMORYARENA_PRODUCT_DATA = Join-Path $assetsRoot 'shopping'

uv run python configs/memoryarena/prepare_assets.py --scene search --output $assetsRoot --worker-python $worker --java-home $env:MEMORYARENA_JAVA_HOME
$env:MEMORYARENA_SEARCH_INDEX = Join-Path $assetsRoot 'search-bm25-utf8'
$env:MEMORYARENA_TOKENIZER_CACHE = Join-Path $assetsRoot 'search-tokenizer-cache\hub'
```

Search 准备过程导出固定版本中的全部 100,195 篇语料，并为官方支持的 BM25 searcher
构建本地 Lucene 索引，无需 embedding 模型。
tokenizer 固定在 `c1899de289a04d12100db370d81485cdf75e47ca`，
worker 要求匹配的 `refs/main` 和离线标志。索引与 tokenizer 文件均记录指纹。
Windows Java 必须显式使用 UTF-8：Anserini 可能在解析失败后仍返回退出码 0，
因此准备脚本还会核对文档数量。

这套配置使用 `configs/memoryarena/search-bm25.yaml`。
原始 `search.yaml` 保留官方 OpenAI 稠密检索选项，需要匹配的 embeddings、
索引映射、语料和 embedding 端点。两套配置均不报告 qrel recall。

按配置 README 设置模型和 judge 凭据后执行：

```powershell
uv run dumemeval prepare --environment-config configs/memoryarena/travel.yaml
uv run dumemeval prepare --environment-config configs/memoryarena/shopping.yaml
uv run dumemeval prepare --environment-config configs/memoryarena/search-bm25.yaml
# 任一准备完成的场景都使用同一评测入口：
uv run dumemeval run --config configs/memoryarena/travel.yaml --no-resume
```

Shopping 本地通信验证使用打乱后的前 1,000 个商品、完整官方搜索索引和一个自编购买固定样例，
将内存占用控制在这台 16 GB 机器可承受的范围内。
完整商品文件已下载，仍为默认配置，但未运行全目录评分。
准备相同的可选通信子集时，添加 `--shopping-smoke-limit 1000`，
并在准备脚本的 Python 环境中提供 `ijson==3.4.0`
（例如 `uv run --with ijson==3.4.0 python ...`）。该子集不能作为全目录评测结果。

## 验证边界与诊断

- Travel：真实 CSV FlightSearch 找到了指定航班；用固定参考提交调用了官方评分器。
  这是工具通信/评分固定样例，不是 Agent 自主生成行程的成绩。
- Shopping：官方 lite 服务执行了搜索、商品点击和 Buy Now；宿主端观测包含购买 ASIN
  和完成状态。上游基于系统时间的价格/目标初始化仍未控制，已写入 provenance。
  对照实验采用 Math，因此该限制不影响这次 Math 对照的有效性。
- Search：官方 BM25 返回语料文档 5412，get_document 返回全文，固定的离线 tokenizer 生成摘要片段。
- Math/Phys：固定版本的官方 HTTP 和评分固定样例覆盖两个注册场景；真实 Agent 对照实验采用 Math。
- 重试、工具权限过期、失败、取消、重置和清理由现有定向集成测试覆盖。已结束的场景服务均已回收。

已归档的合成记忆探针也完成了无需模型调用的重新分析，观测到一次文件写入和两次结构化读取，
其中一次读取发生在全新的第二会话。早期记忆操作计数为 0 的报告作为历史记录保留；
新审查和对照实验使用修正后的观测逻辑。

基线仓库评测模型迁移未完成所导致的无关失败，仍记录在历史校验清单中，
不属于 Issue #4。此次验收不要求运行完整评测集或重复完整测试套件。
