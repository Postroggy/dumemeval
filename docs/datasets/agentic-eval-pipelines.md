# 各数据集的官方评测步骤不一样

- 状态：draft（已核对的写在表里；缺口在文末）
- 源码：`src/dumemeval/datasets/benchmarks/` · `src/dumemeval/environments.py`
- 关联：`docs/datasets/README.md` · `docs/execution/task-environment-layer.md` · `docs/architecture/run-artifacts.md`

这里只写核对过官方文档、官方代码或本仓库适配器的内容。没打开官方 runner 逐行对的，标「未核实」。本仓库映射和官方不一致的，标「已知偏差」。

不要把本文当成「所有 agentic 数据集共用一条 pipeline」——它们不共用。

用词（和 README「一次评测里有几层」一致）：

- **本仓库 task**：互相不共享 memory 的单位
- **本仓库 session**：agent 跑一轮，不是「一段连续对话」
- **官方 session / round / chunk**：各数据集自己的字段，下文用全称

---

## 1. 先说结论

1. LoCoMo 这类：官方是先把历史对话变成记忆，再问答。本仓库 locomo 适配器是先全部 ingest、再全部 qa，不是喂一段立刻问一题。
2. 带环境、带工具、带反馈回路的数据集，官方步骤各不相同。至少要分清：有没有外部环境、记忆是 agent 自己写还是脚本灌进去、分数看环境终态还是看文本。
3. 本仓库用同一套 `task → session → trial` 去接。骨架相同，不等于官方步骤相同。常见接错：该走 env server 的任务，被写成一大段 instruction。

「Agentic Memory」在论文和 README 里用法不统一。本文不另下定义，只引用各仓库自己的说法。

---

## 2. 对照表（已核实）

| 数据集 | 官方自称 | 有独立 env server / 工具环境？ | 官方记忆怎么进系统 | 官方主判分 | 本仓库 `build_tasks` | 已知偏差 |
|---|---|---|---|---|---|---|
| MemoryArena shopping | multi-step product search and purchase；早期购买写入 memory 供后续检索（`setup_web_shopping.md`） | 有：`env/env_server.py`，动作 `search[]` / `click[]` | 官方描述为购买结果存 memory；具体 write API **未在本文逐行核对** `run_shopping.py` | ASIN exact match 等（适配器 docstring：官方 `match_ground_truth`） | 1 样本 → 1 task；每回合 1 session；`task_environment.type: webshop` | 官方分依赖 webshop 商品库+env server；未起则 ASIN 分可为 0 |
| MemoryArena travel | group travel；ReAct 调 FlightSearch 等；Previous travelers' plans stored in memory（`setup_travel.md`） | 官方有：旅行工具 + 本地 CSV 库 | 同上，**未逐行核对** `run_travel.py` | slot 相似度 + `judgement_mode`（calculator：官方 `travel_env.py`） | 1 样本 → 1 task；可选先注入 `base_person`，再每 round 1 session | **适配器未设置 `task_environment`**，instruction 是规划文本，不是官方工具循环 |
| MemoryArena search | BrowseComp-Plus 作为 env 之一（`setup_web_search_env.md`） | 官方有：env_server + FAISS 检索 | **未逐行核对** `run_search.py` | GRADER_TEMPLATE → accuracy（官方 `search_agent/prompts.py`） | 1 样本 → 1 task；每个 question 1 session | **适配器未设置 `task_environment`** |
| MemoryArena math/phys | Formal reasoning；env `math` / `phys`（`setup_formal_reasoning.md`） | 官方有：env_server（文档示例端口 8001） | 配置里有 `session_wise_memory` 等字段；**记忆写入时机未逐行核对** | `math_env.judge` → `is_correct`（phys 共用） | 1 样本 → 1 task；每个 subtask 1 session；instruction = backgrounds + question 原文 | **适配器未设置 `task_environment`** |
| MemoryAgentBench | Incremental Multi-Turn；「inject once, query multiple times」；context 切 chunk（官方 README + `conversation_creator.py`） | **无** webshop 类环境；是 AgentWrapper + 各 memory 后端 | 官方：`_memorize_context_chunks` 把 chunks 记入 agent，再逐 query（`initialization.py`） | 按 `metadata.source` 分流（substring / exact / Recall@5 / judge） | 1 条 context → 1 task；**每个 chunk 一个 ingest session**，再每题 1 qa session（`chunk_size` 默认 4096） | 官方 `send_message(..., memorizing=True)` 的 prompt 模板未逐字抄入 instruction；chunk 边界与官方 tiktoken+punkt 的逐样本 parity 报告未做 |
| StreamMemBench | Streaming Evaluation of Agent Memory（官方 README） | **无** 外部商店/旅行环境 | 官方 `docs/evaluation.md`：ingest stream → 首答 → feedback → 必要时改答并写回 memory → follow-up | 四指标：fidelity / initial_evidence_use / feedback_incorporation / followup_reuse | 每个 evidence anchor → 1 task；**3 session**：stream 文本 / initial_request / followup_request | **未实现官方第 4–6 步**（feedback 模拟、改答、写回后再问） |
| BEAM | 长上下文记忆问答，10 类（适配器 docstring） | 无 | 本仓库：整段 `context` 一次注入 | LLM judge 按 rubric（官方 `compute_metrics.py`） | 1 题 → 1 task；2 session（读 context / 答题） | 与「环境行动式 agentic」不是同一管线；是否等于官方 10M 流式设定 **未用官方 runner 核对** |
| LongMemEval | 长对话记忆 QA（适配器：ICLR 2025） | 无 | 本仓库：注入该题 `facts`，再答题 | anscheck 模板 + abstention（官方 `evaluate_qa.py`） | 1 题 → 1 task；2 session | 数据里有 `sessions` 字段，**适配器未按官方 session 列表逐段喂入**（只用了 facts） |
| HaluMem | 记忆幻觉；官方强调不要只看端到端 QA（官方 README） | 无 | 本仓库：注入 user.dialogue，再逐题 | 三阶段 prompt（integrity / interference / update / QA） | 1 user → 1 task | 适配器注明：本地常缺 HF 完整三阶段字段（`extracted_memories` 等） |
| Memora | 遗忘感知 FAMA（calculator：官方 `model_based_evaluator.py`） | 无 | 本仓库：session 1 注入记忆，session 2 答主问题 | FAMA = max(0, MPA − λ(1−FAA)) | 1 题 → 1 task | 适配器 **无 `Source:` URL**（只有 Paper）；官方 runner 是否「注入+一问」**未核对** |
| EverMemBench-Dynamic | 长周期多方对话记忆（HF README：~250 天群聊） | 无 | 本仓库：注入该 topic 完整群聊，再逐题 | MC 规则 + OE LLM judge | 1 topic → 1 task | 官方是否按日期流式 ingest **未核对** |

MemoryArena 四个环境**共用同一套官方 hosting**（`env/env_server.py` + `env_client.py`），但**任务动作空间和判分不同**，不能当成一个 benchmark 抄同一套 session 指令。

---

## 3. 分数据集：官方管线 vs 本仓库映射

### 3.1 MemoryArena shopping（行动 + 链式购买）

**官方（`vendors/MemoryArena/setup_web_shopping.md`）**

- Agent 在模拟商店里用 `search[query]` / `click[element]`，每回合一个动作。
- 「Purchases from earlier steps are stored in memory and retrieved to inform later ones.」
- 数据从 HF `ZexueHe/memoryarena` 加载（文档写 config `web_shopping`；本仓库 prepare 拉的是 `bundled_shopping/data.jsonl`，config 名是否完全等同 **未再核对 HF 页**）。
- 运行：先起 `python env/env_server.py`（默认 :8005），再 `run_shopping.py`。
- 代码路径自称不依赖 `agentenv_webshop/` 等旧树。

**本仓库**

- `memoryarena_shopping.py`：每个 jsonl 行 → 一个 `EvalTask`；`questions[i]` → 一个 session；`task_environment = {type: webshop, ...}`。
- instruction 要求经 `TASK_ENV_URL` 走 search/click/Buy Now，不把商品目录摊进文本。
- 判分：`MemoryArenaShoppingCalculator`（ASIN exact match 等）。
- 框架只暴露 endpoint / hint / env（`environments.WebshopTaskEnvironment`）；**不内嵌商品库**。

**必须澄清**

- 跨回合依赖的是：**记忆里的已购信息 + webshop server 侧状态**（官方购买结果在 env 的 `info.last_purchased_asin` 一类字段上打分）。两者都不是「把上一回合的 prompt 历史留在同一容器上下文里」。
- `memory.type: none` 只表示框架不接**外部第三方 memory 后端**；hermes/Claude 是否仍用 runtime 自带 memory，框架不观测。

### 3.2 MemoryArena travel / search / math·phys

**官方**

- Travel：链式多人行程；工具 FlightSearch、RestaurantSearch 等；本地 CSV 库；「Previous travelers' plans are stored in memory」（`setup_travel.md`）。
- Search：BrowseComp-Plus 挂在同一 env hosting 上；agent 脚本同时打 env 与可选 memory server（`setup_web_search_env.md`）。
- Math/Phys：独立 env（文档示例 `env_name: math`，`base_url` 8001）；配置可含 `session_wise_memory`（`setup_formal_reasoning.md`）。

**本仓库**

- Travel：`base_person`（若有）→ 一个 ingest 式 session，然后每个 planning round 一个 session。当前接入只报告 `derived_round_success` / `derived_slot_accuracy`，不代表官方 PS/SPS/SR。
- Search：每个 question 原文作为一个 session。指标 `accuracy`。
- Math/Phys：每个 subtask 的 instruction = 该条 `backgrounds` + `questions` 原文。指标 `is_correct`。

**已知偏差（事实，不是猜测）**

- 这三个适配器的 `build_tasks` **都没有**写 `task_environment`。
- 因此默认跑起来是「文本 instruction + 框架 memory 生命周期」，**不是**官方 ReAct 工具环，除非用户在 yaml 里自行加 `task.task_environment` 且已注册对应 provider。
- 目前 `environments.py` 内置 provider 只有 `http` 与 `webshop`。travel / browsecomp / math **没有**内置 provider。

### 3.3 MemoryAgentBench（增量多轮，但不是环境行动）

**官方（README + `initialization.py` / `conversation_creator.py`）**

- 标题：Evaluating Memory in LLM Agents via Incremental Multi-Turn Interactions。
- 四能力：Accurate Retrieval、Test-Time Learning、Long-Range Understanding、Conflict Resolution。
- 数据切成 chunks，「simulate real multi-turn interaction」。
- 设计哲学原文：inject once, query multiple times（一份长文本对应多问）。
- 流程：`ConversationCreator.get_chunks()` → `initialize_and_memorize_agent`（无存档则 `_memorize_context_chunks`）→ 再对 query 作答。
- AgentWrapper 支持 long context / Letta / Mem0 / Cognee / 多种 RAG，**不是** MemoryArena 那种 env_server 动作环。

**本仓库**

- 每个 parquet 样本（整段 `context` + `questions`）→ 一个 task。
- `chunk_text_into_sentences`（tiktoken gpt-4o-mini + nltk 句切，默认 `chunk_size=4096`）把 context 切成块；每块一个 ingest session；每题一个 qa session。顺序：先全部 ingest，再全部 qa。
- 设计说明：`docs/datasets/memoryagentbench.md`。

**已知偏差**

- 官方 ingest 是 `agent.send_message(chunk, memorizing=True)`；本仓库是 Harbor session + instruction「阅读并记住该块」。prompt 模板未逐字抄官方 `utils/templates.py`。
- 未做与官方 runner 的逐样本 chunk 数 parity 报告。

### 3.4 StreamMemBench（流 + 反馈回路）

**官方（`docs/evaluation.md`）** 对每个 evidence anchor：

1. Ingest the stream segment  
2. Capture newly saved memory records（fidelity）  
3. Ask `initial_task.user_request`  
4. Generate or receive `feedback`  
5. 若反馈要求修改，带着 feedback 再答同一请求  
6. Store the evaluated interaction back to the memory system  
7. Ask `followup_task.user_request`  
8. Score  

默认 `fidelity_mode` 是 `saved_records`（审计 ingest 时新写入的记录）。指标四项均为 0/1，聚合均值在 [0,1]。

**本仓库**

- 每个 evidence anchor → 一个 task。
- 三个 session：stream 文本、initial `user_request`、followup `user_request`。
- **禁止**把 `evidence_statement` / `expected_behavior` 写进 agent instruction（官方禁止泄漏）；它们只进 `task.data` 给 calculator。

**已知偏差**

- 没有第 4–6 步：无 FeedbackSimulator、无「改答后再写回 memory」、因此 `feedback_incorporation` 在真实官方意义上**无法按 8 步轨迹算全**（calculator 若仍出该键，语义需对照 `metrics/benchmarks/streammembench.py`——**待社区打开 calculator 与官方 EvaluationRunner 做 parity**）。

### 3.5 BEAM / LongMemEval（长上下文 QA，不是 MemoryArena 那种 agentic）

**BEAM（本仓库 + 本地 `aml_input_beam.jsonl` 抽样）**

- 每行一题：`context`（抽样见约 5e5 字符级长对话，含 `[March-15-2024]` 时间标记）+ `question` + `rubrics` + `question_type`。
- 适配器：2 session（注入 context / 答题）。判分 LLM rubric。
- **未**用官方 `run_evaluation.py` 核对「是否必须整段注入、是否还有 10M 流式设定」。

**LongMemEval**

- 适配器：每题 2 session，ingest 的是 `question_content.facts`，不是数据里的 `sessions` 列表。
- 数据模型里存在 `sessions: list[dict]`，**本仓库未使用该字段做逐段 ingest**。官方 `evaluate_qa.py` 是否用完整 session 轨迹，**待社区核对**。

二者都没有 `task_environment`。把它们叫做 agentic，容易和 MemoryArena 混淆；更准确的说法是：**长上下文 / 长对话记忆 QA**。

### 3.6 HaluMem / Memora / EverMemBench-Dynamic

**HaluMem（官方 README）**

- 批评「只拿端到端 QA 评 memory」。
- 本仓库：dialogue ingest + 逐题；calculator 对齐三阶段 prompt。
- 适配器写明完整三阶段需要 HF 上带 `extracted_memories` / `questions` 的格式；本地 stage 可能不齐。

**Memora（calculator 对齐 `model_based_evaluator.py`）**

- FAMA 公式已在本仓库实现并注明行号。
- 适配器组织：每题 2 session（注入 / 主问题）。官方 evals 是否同一划分，**未读官方 runner**。
- **缺 `Source:` 仓库 URL。**

**EverMemBench-Dynamic（HF README + 适配器）**

- HF 描述为 ~250 天多方对话。
- 本仓库：每个 topic 的 `dialogue.json` 一次注入，再跑该 topic 的 QA。
- 是否应按日期流式 ingest：**未核对官方评测脚本。**

---

## 4. 必须单独澄清的细节（避免评测写错）

### 4.1 「跨 session 记忆」发生在哪一层

| 范围 | 本仓库行为 | 适用 |
|---|---|---|
| 同一 task 里的各轮 session | `memory_session_transfer`：inject / snapshot / collect | locomo 一篇对话；shopping 一个样本的多回合 |
| 不同 task 之间 | 默认隔离（每个 task 自己的 adapter 目录 / transfer 子目录） | locomo 的 conv-26 和 conv-30 是不同说话人，不该共用记忆 |

不要把「agentic 要演化」理解成「所有 task 共用一个 memory」。MemoryArena 官方样本是**组内回合依赖**，不是 270 个 travel group 共用一本记忆。跨样本长期演化若要做，需要新的作用域约定（当前没有）。

### 4.2 隔离的是工作上下文，不是记忆库

Harbor 默认**每一轮 session 一个 Trial / 容器**。上一轮的 prompt 历史不会带到下一轮。

记忆仍可以跨回合留下：

- 工作上下文：每轮清空，逼 agent 用 memory 工具或注入通道，而不是翻聊天记录
- 记忆库：directory 挂载、HTTP 服务、或 MemoryTransfer 搬走容器里自写的文件
- 任务环境：webshop 等 server 自己保存商品和已购状态

MemoryTransfer 只处理「写在容器里、又没挂到宿主机」的文件。外接 HTTP memory 不用它搬库（`adapters/http.py` 只注入 `MEMORY_SERVER_URL` 一类环境变量）。

### 4.3 判分不在 Harbor 容器里（默认）

默认容器 verifier 是空操作（`execution/task_dir.py`）。LLM judge 和官方口径在宿主机 `finalize_run` 里算，等全部 trial 跑完后按 task **串行**计算。并发只发生在跑 agent 的阶段。

### 4.4 本仓库的 session ≠ locomo JSON 的 `session_1`

locomo 数据里的 `session_1..19` 是对话分段。本仓库里每一段 ingest、每一道 qa 各是一轮 agent。一篇对话 = 一个 task = N+M 轮。见 README「一次评测里有几层」。

### 4.5 locomo 的顺序

不是喂一段立刻问一题。`LoCoMoAdapter.build_tasks` 是 `ingest_sessions + qa_sessions`：先喂完这篇对话留下的各段，再逐题问。

---

## 5. 扩展点怎么用（按数据集选，不是新设计）

现有扩展点已经能表达差异，但**接法必须按数据集选**：

| 官方差异 | 应对的扩展点 | 现状 |
|---|---|---|
| 要在商店/工具环境里行动 | `register_task_environment` + yaml `task.task_environment` | shopping 已接 webshop；travel/search/math 适配器未接 |
| 只要跨回合传递记忆 | `memory_session_transfer` + adapter | 通用 |
| 官方先 chunk 再问 | `build_tasks` 必须按官方粒度切 session | MemoryAgentBench 已按 chunk ingest（prompt 模板 / parity 报告仍待补） |
| 官方有 feedback 再问 | 需要额外 session 或新协议钩子 | StreamMemBench 未做 |
| 只做长上下文 QA | 2 session 注入+问答即可 | BEAM / LongMemEval 当前如此 |

加数据集时：先按本文把官方步骤写清楚，再写 `build_tasks` 怎么对应。不要拿 shopping 的 webshop 指令去套 travel，也不要用 locomo 的 F1 去打 ASIN。

---

## 6. 还没核对的（欢迎补，不要猜）

补 `docs/datasets/<name>.md` 时带上：官方文件路径、行号或原文、本仓库函数名。

1. MemoryArena 的 `run_shopping.py` / `run_travel.py` / `run_search.py` / `run_math.py`：记忆是 agent 用工具写的，还是 runner 调 wrap/add？和 `session_wise_memory` 什么关系？
2. HF 上的 config 名：`setup_web_shopping.md` 写 `web_shopping`，本仓库路径是 `bundled_shopping`，是不是同一份 split？
3. MemoryAgentBench：同一 `chunk_size` 下，本仓库 ingest 轮数是否等于官方 `get_chunks()` 的长度。
4. StreamMemBench：现在只有 3 轮、没有 feedback 步时，四个官方指标实际算了什么？对照 `EvaluationRunner`。
5. LongMemEval：官方是否用数据里的 `sessions` 全轨迹；只喂 facts 会不会改 anscheck。
6. BEAM：100K 和 10M 两套设定；`event_ordering` 的 Kendall τ 本仓库是近似（calculator 已写明）。
7. Memora：补适配器 `Source:` URL；官方是不是「每题两步」。
8. EverMemBench-Dynamic：官方是否按日、按群流式 ingest。
9. HaluMem：HF 完整字段怎么对上三阶段脚本。
10. travel / search / math 的 `task_environment`：要官方工具环就得新 provider，没接上之前不要写「已对齐官方环境」。

---

## 7. 本文没写的

- 未在本地打开的论文段落（除适配器已引用的 arXiv 号）
- 「所有 agentic 数据集都应每回合新容器」或「都应共用容器」——这是执行层取舍，不是数据集官方管线事实
- Letta Leaderboard / 未进入本仓库适配器的基准的评测步骤
- 对官方记忆写入 API 的猜测性时序图
