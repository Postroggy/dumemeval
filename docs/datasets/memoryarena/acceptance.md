# MemoryArena Issue #4 验收报告

本页对应 [Issue #4](https://github.com/Postroggy/dumemeval/issues/4) 的交付物和 15 条验收标准。
设计与官方差异见 [README](README.md)，复跑命令见[运行指南](clean-setup.md)，版本与哈希见
[sources.json](sources.json) 和 [verification.json](verification.json)。

实现已 rebase 到 `master` 的 `1b48fc3`。2026-09-17 的检查对应历史提交 `1a132d0`，
不能证明后续 PR head 的类型检查或 CI 已通过。2026-09-18 review 修复的结果单列于下方，
真实模型材料仍属于其原始执行版本。
以下是交付方的验证记录，最终验收由维护者完成。

## 验收清单

| # | Issue 要求 | 实现与证据 |
| --- | --- | --- |
| 1 | 五场景锁定官方版本，记录入口/数据/环境/评分/许可证 | `sources.json` 固定源码 `6cd9de1`、数据 `da1a37c` 和关键文件哈希；未声明许可证如实记录；README 给出五场景契约。 |
| 2 | 五场景走统一评测入口 | 五套场景 YAML 与已注册 adapter/provider/calculator；`test_cli.py` 验证统一入口。实际工具验证见下表，未声称五场景全量实跑。 |
| 3 | 保留官方任务与评分语义 | 逐商品 Shopping ASIN、商品属性字符串匹配、Travel 六槽位 PS/SPS/SR、Search 最终 query、Math/Phys paper 聚合已有实现。Travel 默认支持官方 on/off 历史交付路径；Shopping LLM 属性 judge 与完整 fallback reward、Search qrel recall 尚未接入。新增 Travel 路径未记录真实模型对照结果。 |
| 4 | 至少一个真实环境完成 Agent 交互 | Math 中 Claude Code、Hermes 的真实 Harbor on/off 各完成 2/2 会话，并调用官方 reasoning/submit。 |
| 5 | 多轮和跨 session memory | 首轮写入、第二独立会话读取首轮快照并更新；off 无记忆挂载。原生轨迹与快照均保留。 |
| 6 | 三类 reset 边界可验证 | 任务/商品环境作用域、全新 Harbor 会话、协议管理的目录记忆分别管理；`test_runtime.py`、`test_completion.py` 及真实轨迹覆盖。 |
| 7 | on/off 控制与样本对齐 | 历史同一完整 Math 样本，实际用户/系统提示和 Skill 一致，9 项当时指纹一致。旧报告缺新增字段，当前自动比较标为未验证，详见下文。 |
| 8 | 五场景 fixture / 已覆盖评分路径对照 | `tests/benchmarks/memoryarena/fixtures/`、`test_official_parity.py` 与 `test_official_travel_shopping.py`；新增 Travel 六槽位人员规则及 Shopping 属性字符串回退与固定官方源码对照。本地 HTTP 中 judge 为确定性固定样例，另有真实 Math judge 正反例。 |
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

## 本轮 review 修复与代码检查

2026-09-18 首轮 review 修复记录于 `verification.json` 的 `review_checks`。随后补入 Travel 官方评分、
on/off 历史路径与 Shopping 属性字符串评分；以下新增验证以本次提交为准，未写入旧证据包。

- FastAPI 路由显式注册，保留 handler 的类型；仅安装 dev 依赖时也能运行 strict mypy。
- Search 受管最终评分要求本轮成功检索证据；没有证据时不调用 judge。answer-only 结果为派生诊断。
- Travel 增加默认官方历史控制路径与六槽位 PS/SPS/SR；旧七槽位诊断仅在显式 custom flow 下使用。新路径已有固定样例和官方源码对照，尚未做真实模型 on/off 实验。
- 评分范围贯穿 JSON、Markdown、Utility 与比较；派生值不再进入 `official_task_score`，不能混入官方聚合。
- Shopping backend 由 runtime 统一管理，版本/依赖参与稳定指纹，端口/清理结果记录于 provenance；固定上游完整 reward 在受管 worker 中计算，`auto` 模式在 LLM judge 无法建立时保留完整字符串回退 reward，目录加载在任务进程内缓存。
- 资源脚本纳入 `make ci` 的 Ruff/mypy 范围，补充离线 manifest 测试；Source 扫描覆盖整个 `src/dumemeval`。

本轮不重新执行付费模型实验，不改变原始真实运行证据。Linux `make ci` 以当前 PR Checks 为准，
Windows 检查不能替代 Linux 门禁。

当前 Windows / Python 3.12.11：`PYTHONUTF8=1` 的全仓非 e2e 测试在排除下节已复现的 3 项
Windows 路径/权限断言后为 771 通过、61 跳过。MemoryArena 专项为 236 通过、44 跳过；
新增 Travel、Shopping 属性与完整 reward/LLM 路径的固定官方源码对照通过。
Ruff、格式、strict mypy（240 文件）、wheel/sdist 构建及四臂 mock smoke 通过。

## 历史代码检查与上游基线（1a132d0）

2026-09-17，Windows / Python 3.12.11；历史实现 `1a132d0`，上游 `1b48fc3`。

| 检查 | 结果与范围 |
| --- | --- |
| 非 e2e 全仓测试 | 748 通过、3 失败、13 跳过；3 项失败均在新上游同环境原样复现，无新增失败。 |
| 官方源码对照 | 33 项通过，已包含在全仓统计中。 |
| Ruff / 格式 / mypy | 全部通过；格式覆盖 229 文件，mypy 检查 228 文件、0 错误。 |
| wheel / sdist | 构建通过。 |
| 示例与 mock smoke | locomo_mini、user_preference 及 locomo/shopping × transfer/test_only 共 6 组通过。 |

Windows 的 3 项失败分别是 Harbor 路径分隔符、POSIX 执行位、索引路径后缀断言；
独立检出新上游、确认导入基线源码后复现，并核对测试函数 AST 与失败断言一致。
GitHub 的 Linux 检查执行仓库统一 `make ci`，状态以 PR Checks 为准。

`checks.zip` 的 `rebase-1b48fc3/` 保存 2026-09-17 的原始日志、JUnit、源码哈希、基线复现及摘要。
`f3fdd92/` 与 `baseline/` 中的旧记录（632 通过/108 失败、152 条 mypy 错误）仅用于历史追溯，
不能继续作为当前提交的检查结果。此前的安装产物和真实模型记录保留原始版本边界。
文档整理检查记录在 `verification.json` 的 `documentation_checks`，历史 rebase 结果在 `rebase_checks`。

<a id="evidence"></a>

## 验收附件

| 附件 | 从哪里开始检查 |
| --- | --- |
| [claude-and-tools.zip](evidence/claude-and-tools.zip) | `results/memoryarena/controlled-final-20260915/` 的 on/off、comparison、原生/ATIF/环境轨迹、快照；`official-assets-20260915/` 的三个外部资源场景。 |
| [hermes.zip](evidence/hermes.zip) | `math/validation.json`、`math/{on,off}/`、`math/prompts/`；`diagnostic/` 与首次 401 失败材料分开。 |
| [checks.zip](evidence/checks.zip) | `rebase-1b48fc3/` 当前检查与 Windows 基线；`f3fdd92/` 历史功能检查；`baseline/` 上游日志；`setup/` 安装验证；`environment-probes/shopping/` 逐商品环境证据；`historical-recomparison/` 旧报告缺失字段警告。 |
| [verification.json](verification.json) | 三个 ZIP 的 SHA-256、结果摘要、历史提交、对照复核与本次整理检查。 |

前两份 ZIP 与原提交字节一致；`checks.zip` 合并保留最终检查和必要基线记录，`origins.json` 给出原档案成员及哈希。
原始运行/检查清单在其中的 `manifests/`，其路径和哈希属于当时版本。当前复跑以运行指南为准。
历次过程说明可在 Git 历史查阅，不再作为当前交付的平级文档。

## 已知差异与未测范围

- 未运行五场景全量数据，未证明正向或统计显著的记忆收益；真实模型结果不代表后续修复代码的重新实跑。
- 两组保持配置及采样设置一致，未声称模型服务提供全局确定性随机种子。
- Shopping 上游按系统时间初始化的随机性未控制，已写入 provenance；Math 对照不使用 Shopping 环境。
- Travel 新增的官方 on/off 路径和尚未实跑的 Shopping LLM/完整 reward 路径只有确定性样例与固定上游源码对照，尚无本次提交的真实 Agent 运行结果；Travel on 历史中的官方 Agent 内部 scratchpad 无法由宿主获取，当前为空。
- Search 多数票是可选扩展，不报告 qrel recall；官方依赖与兼容 worker 的差异已记录。
- Hermes 的 Harbor ATIF 未携带会话级 token 统计；框架 token/cost=0 表示未测，原生用量另存，费用未知。
- 记忆观测是下界：Claude 结构化 Read 可自动计数，Hermes 使用原生读取证据；任意 shell 读取或写后恢复原内容可能无法计数。
- 验证平台为 Windows + Docker Desktop Linux 容器；原生 Linux 宿主路由和新账号交互登录未复验。
