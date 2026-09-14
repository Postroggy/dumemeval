# 零依赖示例

| 文件 | 做什么 |
|---|---|
| `locomo_mini.yaml` + `data/locomo_mini.json` | 自造 LoCoMo 格式迷你对话，`make example` 验证装完能跑。**不要当真跑数据。** |
| `user_preference.yaml` | 手写 2-session 偏好记忆，`make mock` 验证编排。 |

```bash
.venv/bin/python -m dumemeval run --config examples/locomo_mini.yaml --mock --no-resume
.venv/bin/python -m dumemeval run --config examples/user_preference.yaml --mock
```
