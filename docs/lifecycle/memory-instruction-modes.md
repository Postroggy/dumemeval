# Memory 使用指令：none / location / proactive

- 状态：implemented
- 源码：`src/dumemeval/core/config.py`（TaskSpec.memory_instruction）· `src/dumemeval/lifecycle/runner.py` · `src/dumemeval/execution/task_dir.py` · 各 adapter 的 `memory_usage_hint`
- 关联：`docs/adapters/memory-injection-contract.md`（注入通道）

## 问题

框架声称评测「agent 会用 memory」，但 agent **从未被告知 memory 存在**：

- 注入通道只提供 env 变量（`DUMEMEVAL_MEMORY_DIR` 等），instruction 原文不提
- hermes 是系统提示注入快照、http 是替 agent 检索——被动喂给
- 结果：agent 用不用 memory 全凭运气；`Trace.memory_tool_used` 测的是「碰巧调没调」，不是「会不会主动用」

**memory 的使用是 agent 的决策**，不告知就测不了这个决策——这是 agent-first claim 与现实之间最大的缺口。

## 方案

`TaskSpec.memory_instruction: none | location | proactive`（默认 `none`，完全向后兼容）：

| 模式 | agent 收到什么 |
|---|---|
| `none` | 原文（不变） |
| `location` | 原文 + 一行：「持久记忆位于 X，需要时可用工具读取」 |
| `proactive` | location + 「回答前先回忆相关记忆；学到值得跨会话保留的信息主动写入」 |

实现路径：

1. `BaseMemoryAdapter.memory_usage_hint() -> str | None`（可选覆写）：adapter 用自己的通道语言描述 memory 在哪（directory → `/app/memory`；hermes → memories 目录；http/everos → 服务地址 + user_id）
2. `SessionRunner` 在 inject 后按模式组合 suffix，写 `session_ctx["instruction_suffix"]`（与 `memory_mounts` 同范式：lifecycle 写契约，执行器消费）
3. `TaskDirGenerator.generate(..., instruction_suffix)` 把原文 + suffix 一起写进 instruction.md

**只在 `session.memory_inject` 且协议允许时追加**——`test_only` 协议下 agent 永远不知道 memory 存在，基线语义不被污染。

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 直接改 `SessionSpec.instruction` | 污染数据集原文（GOVERNANCE 明令 instruction 用原文）；suffix 必须可分离 |
| 在 adapter.inject 里各自拼 instruction | 四个 adapter 各写一份文案，措辞漂移；模式语义（none/location/proactive）是评测设计，归 lifecycle |
| 默认 proactive | 改变所有现有评测的语义；memory 使用是否「被要求」本身就是实验变量，必须显式选择 |
| 只改 env 变量名让 agent 自己发现 | agent 不会读不存在的文档；「发现 memory」不是被测能力，是偶然事件 |

## 语义边界

- suffix 只声明**能力和位置**，不代劳内容——不把记忆内容贴进 instruction（那是注入通道的职责）
- 本模式的 `none` 与 `memory.type: none` 是两回事：前者只决定「是否告诉 agent memory 存在」（原文不变）；后者表示框架不接入任何外部第三方 memory 系统——**不代表被测 agent 没有记忆能力**（agent runtime 自带原生 memory 是 runtime 的属性，见 docs/adapters/memory-injection-contract.md）
- `proactive` 下 agent 仍可能不用 memory：这正是 `Trace.memory_tool_used` 要测量的——从「碰巧」变成「决策」
- `location`/`proactive` 模式本身会抬高分子任务的成功率：跨模式比较时这是自变量，不是噪声；compare 的可比性警告不覆盖它，**跨 memory_instruction 模式的 run 对比需在报告中自行注明**

## 验证

- `tests/test_memory_instruction.py`：benchmark 构建路径的回填断言（proactive / 默认 none / task_environment）+ test_only 协议 × benchmark 归一化
- `tests/test_agent_first_gaps.py`：runner 级 suffix 断言——三种模式组合 directory adapter → suffix 内容；`none` 不写 suffix；`test_only` 协议不追加；TaskDirGenerator 落盘 instruction.md 含原文 + suffix
- 既有测试不改（默认 `none`）

## 未完成

- suffix 文案未国际化（中文硬编码）；面向国际社区时需抽出文案表
