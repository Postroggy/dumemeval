# 安全策略

## 支持版本

项目处于 0.x（当前见 `pyproject.toml` 的 `version`），只维护最新发布版。报告时请附版本号。

## 报告漏洞

不要在公开 Issue 里写可利用细节。

- 优先：GitHub `Security → Report a vulnerability`（private advisory），维护者 [@Postroggy](https://github.com/Postroggy)。
- 没有以上通道时，才开公开 Issue：标题标 `[SECURITY]`，正文只写受影响模块、影响面、复现概要，不放 POC / 密钥。细节等维护者私下联系后再补。
- 我们会在 5 个工作日内回复确认。

报告请说明：受影响版本、复现步骤、你判断的影响面。

## 本项目的威胁模型

DuMemEval 是**评测框架**，会执行 agent、调用 LLM API、在容器里跑不受信代码。使用者需要知道：

| 面 | 说明 |
|---|---|
| **agent 执行** | Harbor 引擎在 Docker 容器里跑 agent（`--permission-mode=bypassPermissions`）。容器不是安全边界的最后一道——不要在生产网络或含敏感数据的机器上跑不受信的 task 定义 |
| **task 定义即代码** | `datasets/` 生成的 instruction 会直接交给 agent 执行。评测第三方数据集前，先看清 instruction 内容 |
| **API key** | 通过环境变量或 `~/.claude/settings.json` 读取，**不写入任何产物**：`experiment_config.json` 会把键名含 `KEY/SECRET/TOKEN/PASSWORD/AUTH` 的值脱敏为 `***` |
| **产物落盘** | `results/` 含 agent 完整 trajectory 与 memory 内容，可能包含被测数据里的敏感信息。默认已 gitignore，分享前自行检查 |
| **prompt 注入** | LLM-as-Judge 读 agent 输出打分；恶意 agent 输出理论上可影响 judge 判分。这是评测有效性问题，不是系统入侵面——但引用分数时需知晓 |

## 不属于安全问题的

- 指标算得不准 / 口径与官方有差异 → 开普通 Issue
- mock 模式分数不真实 → 设计如此，报告已带「不可引用」横幅
- Harbor / Docker 自身的漏洞 → 报给上游

## 依赖

依赖版本锁在 `uv.lock`。发现依赖漏洞请一并说明是否影响本项目的实际调用路径。
