---
name: trace-memory-analysis
description: >
  对生产 agent 的执行 trace（会话轨迹）做 memory 行为分析。回答三个问题：agent 记不记（写入行为）、
  记忆系统行不行（容量/成功率/机制）、不记/记不住的成本（重复劳动/浪费）。输入一批会话 JSON
  （含 tools/system_prompt/messages），产出基础画像 + memory 行为指标 + 结论先行的分析报告。
  触发信号：分析 agent trace、评估 memory 行为、看记忆系统现状、哪些会话有 memory 调用、
  记忆版本演化、重复命令/浪费率、容量溢出、写入成功率。适用于任意 agent（Hermes/Claude Code 等）
  的会话导出，不要求被测系统是 Hermes。
---

# Trace Memory Analysis

对一批生产 agent 执行 trace 做 memory 行为分析，产出「结论 → 证据 → 含义」结构的报告。

**本文件是工作流主干，刻意简短。深度在 `references/`，引擎在 `scripts/`，模板在 `templates/`。**

## 何时使用

- 用户给了生产会话轨迹（session JSON / 导出目录 / zip），要评估 agent 的记忆行为；
- 想知道：记忆用没用、写不写得进、有没有重复劳动、Skill/memory 载体怎么分；
- 想沉淀某批 trace 的 memory 基线，为记忆系统改进或评测提供输入。

**不做**：LLM 应用性能（latency/error 类）分析（那是 observability 的职责）；单会话逐条质量打分。

## 工作流（8 阶段，可用 --phase 分段执行）

```
① 收集  ② 组织  ③ 机制摸底  ④ 基础画像  ⑤ 深度分析  ⑥ 交叉验证  ⑦ 结论提炼  ⑧ 产物
```

| 阶段 | 做什么 | 关键产物 |
|---|---|---|
| **1 收集** | 向数据方要会话 trace（含 tools/system_prompt/messages）、MEMORY.md/USER.md 最终态、Skill 包、state.db；用 grep 筛出有 memory/检索行为的子集 | 数据清单 + 筛选命令 |
| **2 组织** | 每批独立目录 + README；统一 `reports/` `scripts/`；原始 zip 保留 | 每批 README（见 templates） |
| **3 机制摸底** | **先搞懂被测系统记忆机制再分析**（见 references/mechanisms.md） | 机制结论 + 在位验证 |
| **4 基础画像** | 规模/任务形态/工具分布/memory 调用/快照版本/时间节奏 → `scripts/analyze.py profile` | profile 报告 |
| **5 深度分析** | 写入成功率/容量/冗余/写放大/演化链/触发/载体 → `scripts/analyze.py memory` | memory 行为指标 |
| **6 交叉验证** | 全量口径核算、可复算、控制变量、归因分离（见 references/pitfalls.md） | 校验记录 |
| **7 结论提炼** | 结论先行、正常现象不当发现、不写道歉弱化（见 references/reporting.md） | 结论 callout |
| **8 产物** | 每批 README + 可视化 + 正式报告（结论→数据概况→发现→机制→边界→方向→下一步） | 报告文档 |

## 快速开始

```bash
# 1. 机制摸底（必做，看被测系统的记忆怎么读写）
#    读 references/mechanisms.md，确认：读取=启动注入还是主动检索？写入=add/replace/remove？容量上限？

# 2. 基础画像（输入 trace 目录 → 输出 profile 摘要）
python3 scripts/analyze.py profile --sessions <trace_dir> --out <out_dir>

# 3. 深度分析（memory 行为指标：成功率/容量/冗余/写放大/触发/载体）
python3 scripts/analyze.py memory --sessions <trace_dir> --out <out_dir>

# 4. 产出结论先行的报告（基于 stats.json 渲染报告骨架）
python3 scripts/analyze.py report --sessions <trace_dir> --out <out_dir> --name "报告名"
```

各阶段产物落 `<out>/stats.json`（机器可读，可复算）。**每个数字必须出自脚本，不手工算。**

## 每阶段必读

| 阶段 | 必读 |
|---|---|
| 3 机制摸底 | `references/mechanisms.md`（机制清单 + 验证手段 + 翻车教训） |
| 4/5 指标 | `references/metrics.md`（指标定义 + 为什么 + 口径） |
| 7 结论 | `references/reporting.md`（结论先行规范 + callout + Do/Don't） |
| 6 质量 | `references/pitfalls.md`（踩坑清单） |

## 产物模板

- 每批 README：`templates/batch_README.md`
- 正式报告结构：`references/reporting.md` 末尾的骨架

## 维护

- 设计决策与候选评测：`docs/EVALUATION.md`
- 改指标口径：改 `references/metrics.md` + `scripts/analyze.py`（两者必须同步，stats.json 字段是契约）
- 新增载体/系统：先更新 `references/mechanisms.md` 的机制表，再在 `TOOL_HINTS` 加归类
