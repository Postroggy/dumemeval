# CI 口径

- 状态：implemented
- 源码：`Makefile` 的 `ci` 目标；`.github/workflows/ci.yml` 只调用 `make ci`

## 测什么

GitHub Actions（push `master`/`main`、所有 PR）和本地 `make ci` 跑同一串零外部依赖门禁：

| 步骤 | 命令 |
|---|---|
| lint | `ruff check` + `ruff format --check` + `mypy`（src + tests，`--strict`） |
| test | `pytest tests/ -m "not e2e"` |
| build | `uv build` |
| example | `examples/locomo_mini.yaml --mock` |
| mock | `examples/user_preference.yaml --mock` |
| smoke-mock | `configs/smoke/` 四臂 `--mock`（locomo/shopping × transfer/test_only） |

`smoke` yaml 含 `${ANTHROPIC_*}` 模板；`make ci` / `make smoke-mock` / `make mock` 注入占位值，不打真实 LLM / 网络。

## 不放进 GitHub CI 的

- `make smoke`：Harbor 真跑，要 Docker、镜像、真实密钥
- `make coverage`：报告用，不是门禁
- pre-commit 的 yaml/eof/空白检查：本地 hook；ruff 已由 `make lint` 覆盖

## 备选方案与否决理由

- **workflow yaml 和 Makefile 各写一套命令**：会漂（对齐前 GitHub 只跑一条 locomo smoke，ruff 路径也和 Makefile 不一致）——否决
- **`act` 当门禁**：能复现 runner，不能消灭双份命令——否决为日常入口
- **tox / nox**：仓库只支持 3.12，过重——否决
