"""lifecycle：memory 生命周期（核心模块）。

承载评测协议的核心：跨 session memory 传递 + 生命周期事件。
- runner.py: SessionRunner（multi-session 编排）
- parallel.py: 跨 task 并行
- checkpoint.py: task 级断点续跑
- memory_transfer.py: 跨 session memory 传递
- hooks.py: 生命周期事件钩子
"""
