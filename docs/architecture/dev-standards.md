# 开发规范

本文是**工程规范的唯一权威来源**。`CLAUDE.md`（AI agent 用；`AGENTS.md` 是它的符号链接）与 `CONTRIBUTING.md` 引用此处，不重复维护。

## 1. 数据模型

- **所有**数据模型用 pydantic `BaseModel`；禁止 `dataclass` / `TypedDict` / `NamedTuple`
- 配置加载必须经 pydantic 校验（禁止裸 dict 传过层边界；模块内部局部变量除外）
- 模型放 `models/`；`Field(...)` 写约束与描述，跨字段校验用 `model_validator`

## 2. 类型注解

- 函数签名完整注解（参数 + 返回值）
- 禁止 `Any` 滥用——能用 `Literal` / `Enum` / 具体模型就不用
- `mypy --strict` 覆盖 **src 和 tests**（统一口径：仓库根目录裸跑 `mypy`，读 pyproject 的 `files` 配置）；本地与 GitHub 都只跑 `make ci`

## 3. 代码质量

- `ruff check`（严格规则集）+ `ruff format` 必须过
- 新增模块必须有对应 `tests/test_*.py`
- **禁止 `except Exception: pass` 吞异常**——可回退场景必须与「真错误」可区分（回退要留日志/标记，真错误抛出）
- 模块超过 300 行是拆分信号（判断依据是「是否在做两件事」，不是行数本身）
- 注释解释「为什么」，不复述「做了什么」；不写「学自 / 借鉴 X」式出处标注，写本设计自己的理由

## 4. 测试规范

| 规则 | 说明 |
|---|---|
| **不打真实 LLM / 网络** | 判分器用注入的 fake / rule；HTTP 用 mock（参考 `test_everos_adapter.py`） |
| **不为了绿改断言** | 行为变更时先更新设计文档，再同步断言并在注释说明原因 |
| **mock 与真实同契约** | 执行器必须消费同一份 session_ctx 契约（见 adapter contract 测试）——mock 与真实「一致地错」是最危险的测试失效模式 |
| **「未测」≠「测得 0」** | 断言缺省值时区分 `None` 与 `0.0` |
| marker | `unit`（默认，无外部依赖）/ `integration`（需 Harbor、Docker 或外部服务，打在文件级 `pytestmark`）/ `e2e`（需真实 agent + key）。CI 跑 `-m "not e2e"` |

## 5. 依赖

- 一律经 `uv` 管理（`uv sync` / `uv add`），禁止手动 `pip install`
- 新依赖必须有不可替代的理由——能用标准库 / 已有依赖实现就不加

## 6. 版本与发布

- 版本号：**`pyproject.toml` 是唯一来源**；`__init__.__version__` 经 `importlib.metadata` 读取，不要手改
- 遵循 SemVer 精神；**1.0 之前**（当前 0.x）：次版本号可含破坏性变更，破坏性变更必须在 CHANGELOG 顶部 + 迁移说明
- 发布检查单：
  1. `CHANGELOG.md` Unreleased 段整理完整
  2. bump `pyproject.toml` version
  3. `make ci` 全绿（含 example / mock smoke）
  4. commit + tag `v<version>` + GitHub Release（正文用 CHANGELOG 该段）

## 7. 文档

- 任何 PR 设计文档先行（见 `docs/README.md`），提 PR 前回改文档与实现一致
- 数据集适配 docstring 必须带 `Source:` 官方来源 URL
- 报告 / 指标语义变更：同步 GOVERNANCE「勿过度解读」
