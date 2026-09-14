# 机制摸底（阶段 3，最易翻车）

**在分析任何指标之前，先确认被测系统的记忆机制。** 机制错了，后面全是废的。

## 必须确认的四件事

1. **读取机制**：记忆怎么进 agent 上下文？
   - 启动时全量注入快照（Hermes：MEMORY.md/USER.md → system_prompt 的 ═ 块）？
   - 还是 agent 主动检索（session_search / RAG）？
   - 注：`session_search`（搜历史会话日志）是独立能力，≠ 记忆检索。用"检索次数少"证明"记忆没用"是错的。
2. **写入机制**：add / replace / remove 的语义？
   - add：追加条目（拒绝空/重复/超限）
   - replace：按 old_text 唯一子串匹配改写（多匹配/未匹配报错）
   - remove：唯一子串匹配删除
3. **容量上限**：字符上限是多少？（Hermes MEMORY.md=2200、USER.md=1375；超限 add/replace 被拒）
4. **载体**：除了 memory，agent 还有哪些经验沉淀通道？（Hermes：Skill 体系 skill_manage patch/write_file 写 references/*.md）

## 验证手段（trace 内可查）

- **tools 列表**是否含 memory 工具 → 机制在位？
- **system_prompt** 是否有 MEMORY 快照块 → 注入生效？
- **快照版本指纹**（提取 ═ 块 → md5）是否随日期演化 → 写入→下次注入链路在工作？
- **memory 调用后的 tool 结果** success:true/false → 写入是否真成功？

## 常见机制（判据速查）

| 系统 | 读取 | 写入 | 容量 |
|---|---|---|---|
| Hermes 内置 | 启动全量注入快照 | add/replace/remove（唯一子串匹配） | 2200/1375 |
| EverOS | /search 主动检索 | /add /flush | 无硬上限 |
| Claude Code auto-memory | 启动注入 memory/ 目录 | 文件写 | 无硬上限 |
| 其他系统 | **读源码/文档确认，不假设** | 同上 | 同上 |

## 翻车教训（实测）

- 曾把 session_search（搜历史日志）当"记忆检索"，得出"记忆没被使用"的错误结论 → 机制不同，对比不成立。
- 曾把"事后补记"（写入集中在会话末尾）当问题 → 这是正常人类时序，不当发现。
