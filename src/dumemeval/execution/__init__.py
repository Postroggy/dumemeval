"""execution：隔离执行层。

承载 agent 在隔离环境里的执行：
- executor.py: SessionExecutor 协议
- mock.py: MockRunner（模拟执行）
- harbor_bridge.py: HarborBridge（Harbor 真实执行）
- trial_config.py: TrialConfig 构建（纯函数）
"""
