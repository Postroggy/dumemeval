# MemoryArena Issue #4 验收报告

本页对应 [Issue #4](https://github.com/Postroggy/dumemeval/issues/4) 的交付物和 15 条验收标准。
设计与官方差异见 [README](README.md)，复跑命令见[运行指南](clean-setup.md)，版本与哈希见
[sources.json](sources.json) 和 [verification.json](verification.json)。

实现检查对应 `f3fdd92`；真实模型材料对应更早的执行版本，后续修改由回归与官方对照验证。
2026-09-17 的整理合并文档和检查附件、更新证据路径，没有重新运行模型或全仓检查。
以下是交付方的验证记录，最终验收由维护者完成。

## 验收清单

| # | Issue 要求 | 实现与证据 |
| --- | --- | --- |
| 1 | 五场景锁定官方版本，记录入口/数据/环境/评分/许可证 | `sources.json` 固定源码 `6cd9de1`、数据 `da1a37c` 和关键文件哈希；未声明许可证如实记录；README 给出五场景契约。 |
| 2 | 五场景走统一评测入口 | 五套场景 YAML 与已注册 adapter/provider/calculator；`test_cli.py` 验证统一入口。实际工具验证见下表，未声称五场景全量实跑。 |
| 3 | 保留官方任务与评分语义 | 逐商品 Shopping、Travel 阈值、Search 最终 query、Math/Phys paper 聚合；33 项固定输入官方源码对照。 |
| 4 | 至少一个真实环境完成 Agent 交互 | Math 中 Claude Code、Hermes 的真实 Harbor on/off 各完成 2/2 会话，并调用官方 reasoning/submit。 |
| 5 | 多轮和跨 session memory | 首轮写入、第二独立会话读取首轮快照并更新；off 无记忆挂载。原生轨迹与快照均保留。 |
| 6 | 三类 reset 边界可验证 | 任务/商品环境作用域、全新 Harbor 会话、协议管理的目录记忆分别管理；`test_runtime.py`、`test_completion.py` 及真实轨迹覆盖。 |
| 7 | on/off 控制与样本对齐 | 历史同一完整 Math 样本，实际用户/系统提示和 Skill 一致，9 项当时指纹一致。旧报告缺新增字段，当前自动比较标为未验证，详见下文。 |
| 8 | 五场景 fixture / 官方 scorer 对照 | `tests/benchmarks/memoryarena/fixtures/` 与 `test_official_parity.py`；本地 HTTP 中 judge 为确定性固定样例，另有真实 Math judge 正反例。 |
| 9 | 官方分数、judge、derived metrics、状态分离 | calculator、verifier observation、TaskExecution 和报告分别保存；相关评分与完成状态测试。 |
| 10 | 失败/超时/跳过/未测/0 分可区分 | 缺证据、执行失败、跳过 judge 和截断任务不产生官方零分；`test_completion.py`、`test_search_scoring.py`。 |
| 11 | 重试无重复写入/动作/评分 | 投递身份与服务缓存、隔离的记忆传递目录、评分检查点；工具重试、任务失败恢复和 `test_scoring_checkpoint.py`。 |
| 12 | 脱敏 Harbor/环境/memory trace 与 provenance | 两份原始运行 ZIP 保持字节不变，包含版本、配置、原生/ATIF/环境轨迹及快照；已知凭据扫描记录保留。 |
| 13 | JSON 可解析、Markdown 可阅读 | 附件的 JSON/JSONL 及 ZIP CRC 重新校验，比较报告保留原始数值与警告。 |
| 14 | 核心执行链复用 | 原注册表、协议、runner、memory adapter、verifier；通用装饰器及 provider 生命周期承接环境，主循环无场景分支。 |
| 15 | 干净环境复现命令、明确未完成项 | 运行指南含固定版本下载、镜像、资源、登录、准备/运行/检查和故障排查；隔离安装/镜像/worker 记录在 `checks.zip` 的 `setup/`。平台和验证边界见下文。 |

<a id="real-runs"></a>

## 真实运行与工具证据

| 验证 | 结果与范围 |
| --- | --- |
| Claude Code 2.1.89 / Harbor 0.22 / GPT-5.5 medium | Math on/off 各 2/2 会话、paper pass rate 均 1.0；on 写入、跨会话读取并更新，off 关闭原生自动记忆且无记忆挂载。 |
| Hermes 0.21.3 / 同样本、同模型 | on/off 各 2/2，会话 ID 均独立且无父会话；每组两次 reasoning 和两次 submit，服务结束后关闭。 |
| Shopping | 真实官方 lite 服务执行 search/click/购买；1,000 商品通信样例及逐商品官方固定输入对照。完整商品文件已准备，未运行全目录评分。 |
| Travel | 官方 CSV FlightSearch 返回指定航班，官方评分器核对固定提交；属于工具/评分样例，未记录 Agent 自主行程成绩。 |
| Search | 官方 BM25 检索文档 5412，get_document 返回全文；固定离线 tokenizer 生成片段，语料含 100,195 篇文档。 |
| Math / Phys | 两场景真实官方 HTTP 生命周期、reset/工具/评分固定样例；真实 Agent 实验选用 Math。 |

Math 使用完整数据行 ID 39、paper `2507.18621`，包含两个问题，按“问题数最少且至少两个，同数取最小 ID”选择，
选择不依据答案或模型表现。两组官方分差为 0。
额外 Hermes 随机标记诊断得到 on 找回、off 返回 UNKNOWN；它是自编记忆通道检查，不是官方评分或记忆收益结论。

Hermes 的真实记录对应 `909e185`。Claude 记录保留执行时源码指纹以及当时未提交文件的执行副本。
重新核对 Hermes 原生轨迹：每轮用户提示一致、四个系统提示一致、四次 `skill_view` 内容一致，9 项历史控制指纹一致。
第二会话 `read_file` 去除显示行号后的内容与第一轮快照完全一致，随后快照发生更新。
这些是原始材料复核，不是最新提交的新模型实验。

历史 summary 缺少后来新增的 `agent_skills`、`observed_prompts`；当前比较器会提示
`experiment comparability is unverified`，保留原分数和差值。附件含带警告的重新比较结果，未回填历史字段。

<a id="checks"></a>

## 代码检查与上游基线

以下为 2026-09-16、Windows / Python 3.12.11 对 `f3fdd92` 的已归档检查；上游为 `37a0e19`。

| 检查 | 实现结果 | 上游基线 / 说明 |
| --- | --- | --- |
| 非 e2e 全仓测试 | 632 通过、108 失败、13 跳过 | 上游 389/109/13；失败身份无新增，修复了一个 CLI 测试。 |
| 相关子集 | 232 通过 | 包含 33 项官方源码对照，不重复计数。 |
| mypy | 152 条错误、31 个文件 | 上游 173 条；按文件、诊断内容与次数比较无新增。 |
| Ruff / 格式 | 通过 / 229 文件通过 | 全仓测试和 mypy 仍未全绿。 |
| wheel / sdist / 安装产物 | 构建通过，154 源码模块核对一致 | 8 项仓库外导入/注册检查、客户端入口、真实官方 Math worker 生命周期通过。 |

上游检查使用已归档的固定提交同环境日志。2026-09-17 再次直接比较当前归档和上游归档，
108 项失败均在上游出现，152 条类型诊断没有新增；没有重新跑上游全仓。
本次文档整理的链接、命令语法、证据哈希和受影响回归结果记录在 `verification.json` 的 `documentation_checks`。

<a id="evidence"></a>

## 验收附件

| 附件 | 从哪里开始检查 |
| --- | --- |
| [claude-and-tools.zip](evidence/claude-and-tools.zip) | `results/memoryarena/controlled-final-20260915/` 的 on/off、comparison、原生/ATIF/环境轨迹、快照；`official-assets-20260915/` 的三个外部资源场景。 |
| [hermes.zip](evidence/hermes.zip) | `math/validation.json`、`math/{on,off}/`、`math/prompts/`；`diagnostic/` 与首次 401 失败材料分开。 |
| [checks.zip](evidence/checks.zip) | `f3fdd92/` 最终功能检查日志；`baseline/` 上游日志；`setup/` 安装验证；`environment-probes/shopping/` 逐商品环境证据；`historical-recomparison/` 旧报告缺失字段警告。 |
| [verification.json](verification.json) | 三个 ZIP 的 SHA-256、结果摘要、历史提交、对照复核与本次整理检查。 |

前两份 ZIP 与原提交字节一致；`checks.zip` 合并保留最终检查和必要基线记录，`origins.json` 给出原档案成员及哈希。
原始运行/检查清单在其中的 `manifests/`，其路径和哈希属于当时版本。当前复跑以运行指南为准。
历次过程说明可在 Git 历史查阅，不再作为当前交付的平级文档。

## 已知差异与未测范围

- 未运行五场景全量数据，未证明正向或统计显著的记忆收益；真实模型结果不代表后续修复代码的重新实跑。
- 两组保持配置及采样设置一致，未声称模型服务提供全局确定性随机种子。
- Shopping 上游按系统时间初始化的随机性未控制，已写入 provenance；Math 对照不使用 Shopping 环境。
- Search 多数票是可选扩展，不报告 qrel recall；官方依赖与兼容 worker 的差异已记录。
- Hermes 的 Harbor ATIF 未携带会话级 token 统计；框架 token/cost=0 表示未测，原生用量另存，费用未知。
- 记忆观测是下界：Claude 结构化 Read 可自动计数，Hermes 使用原生读取证据；任意 shell 读取或写后恢复原内容可能无法计数。
- 验证平台为 Windows + Docker Desktop Linux 容器；原生 Linux 宿主路由和新账号交互登录未复验。
