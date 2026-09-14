# 配置语义完善（四合一）

- 状态：draft → implemented
- 源码：`core/config.py` · `datasets/loader.py` · `datasets/prepare.py` · `config/loader.py`
- 关联：docs/datasets/prepare.md · docs/execution/smoke-matrix.md

## 问题

四个配置语义缺口，都让用户「第一次就卡住」或「跑完才发现理解错了」：

1. **数据路径三套体系并存**：`data.type: local/hf/git`、`dumemeval prepare` 缓存
   （`~/.cache/dumemeval/datasets`）、`DUMEMEVAL_DATA_DIR` 覆盖——用户不知道
   什么时候该写路径、什么时候缓存会自动命中、`../../Dataset/...` 这种维护者
   本机路径为什么会出现在配置里。
2. **sessions 占位语义是隐式的**：benchmark 路径下 `task.sessions` 是占位
   （真实 sessions 由适配器 build_tasks 生成），但配置模型没有显式标记——用户
   误改占位 instruction 不会报错，只是被静默覆盖。
3. **`memory.config` 是开放 dict**：hermes_builtin / everos 各自的键
   （`targets`/`memory_limit`/`top_k`/`method`…）散落在 `config` 里，配错键
   要到 adapter 运行期才炸，加载期不报。
4. **`judging.prompt` 与 verifier 注册表不同步**：`JudgeSpec.prompt` 只锁
   `memory_qa/memory_quality/task_success` 三个，但 `LLMJudgeVerifier`
   `_PROMPT_TEMPLATES` 有五个（还差 `math_equivalence`/`search_grader`）；
   且「judging.prompt 是 Quality 默认、benchmark 计算器会覆盖」这个语义只在
   verifier/llm.py 注释里，配置模型没写。

## 方案

四项互不依赖，各自独立落地：

### 1. 数据路径：逻辑数据名（`DatasetSpec.name`）

引入**逻辑数据名**注册表，用户写「要哪个数据集」，框架负责找文件：

```yaml
task:
  benchmark: locomo
  data:
    type: local          # 保留，path 缺失时按 name 解析
    name: locomo_smoke   # 新：逻辑名
```

- `datasets/prepare.py` 新增 `DATASET_REGISTRY`：逻辑名 → `{bundled: 仓库内相对路径|None, cache: 缓存相对路径|None}`。
- 解析顺序：**仓库捆绑 `data/smoke/` → prepare 缓存**（`DUMEMEVAL_DATA_DIR` 已内置在 `cache_root()`）。
- `LocalPathLoader.load()`：`path` 缺失/为空且给了 `name` → 走注册表解析；找不到给出提示
  （`dumemeval prepare` 或设 `DUMEMEVAL_DATA_DIR`）。
- `configs/smoke/*.yaml` 改用 `name: locomo_smoke` / `name: shopping_smoke`；
  `configs/backends/*.yaml` 改用 `name: locomo` / `name: bundled_shopping`——
  从此配置里不再出现任何本机/缓存路径。
- 维护者本机路径语义从「配置里写死」收敛为「注册表 + 缓存」，`doctor` 数据检查
  也走同一注册表。

### 2. sessions 占位显式化（`SessionConfig.placeholder`）

```yaml
task:
  benchmark: locomo
  data: {type: local, name: locomo_smoke}
  sessions:
    - instruction: "（由 benchmark 适配器生成）"
      placeholder: true     # 新：显式声明这是占位
```

- `SessionConfig` 加 `placeholder: bool = False`。
- `TaskSpec` validator：benchmark+data → 要求所有 session `placeholder=true`
  （否则报错「会被适配器覆盖，请标 placeholder」）；非 benchmark 路径 →
  `placeholder=true` 报错「没有适配器生成 sessions」。
- benchmark 无 data：sessions 是真实指令（placeholder=false），按现状走协议校验。

### 3. `memory.config` 类型化（内置 adapter 校验）

`config` 字段保持开放 dict（社区 adapter 需要），但内置类型加类型化校验模型：

```python
class HermesBuiltinConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")   # 未知键直接报错
    targets: list[Literal["memory", "user"]] = ["memory", "user"]
    memory_limit: int = 2200
    user_limit: int = 1375
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None

class EverOSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: str = "locomo_benchmark"
    project_id: str = ""
    method: Literal["agentic", "hybrid", "vector", "keyword"] = "agentic"
    top_k: int = 10
    batch_size: int = 25
    ready_wait_sec: float = 0.0
```

- `MemoryBackendSpec` 加 `model_validator`：`type` 命中内置注册表 → 用对应模型
  校验 `config`（未知键/类型错 → 加载期 ValidationError）。
- 社区 adapter 不受影响（不在注册表 → 不校验）。

### 4. `judging.prompt` 对齐 verifier 注册表 + 语义注释

- `JudgeSpec.prompt` 的 `Literal` 从 3 个扩到 5 个（补 `math_equivalence`、
  `search_grader`），与 `LLMJudgeVerifier._PROMPT_TEMPLATES` 完全一致。
- Field description 写明语义：**judging.prompt 是 Quality/非 benchmark 判分默认；
  benchmark 路径由计算器自己的口径 prompt 覆盖（透传只带 model/key/多数票）**。
- 加同步测试：`JudgeSpec` 可选 prompt ⊆ verifier `_PROMPT_TEMPLATES`，防止再漂移。
  （core 是底层不能 import verifier，所以用测试锁同步，与 protocol 注册表同模式。）

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 数据路径只靠文档解释，不改模型 | 正是要消除的摩擦；文档说十遍不如配置里一个 `name` 字段自解释 |
| `name` 解析失败时静默回退 | 找不到要明确报错 + 给下一步提示，静默回退会重复「0 分不知道谁的错」 |
| placeholder 用指令字符串 `"（由 benchmark 适配器生成）"` 当标记 | 字符串匹配脆弱、用户可能改字；布尔字段显式且可校验 |
| `config` 改造成 `dict[str, Any] \| HermesBuiltinConfig \| EverOSConfig` 联合类型 | pydantic 联合类型报错信息差、社区 adapter 透传被锁死；开放 dict + 校验器更兼容 |
| `JudgeSpec.prompt` 改成开放 `str` | 失去加载期校验；Literal + 同步测试既保留校验又不锁死 verifier 扩展 |

## 语义边界

- `name` 解析只覆盖**内置官方数据**（locomo / shopping 两组）。自备数据仍用显式 `path`。
- `memory.config` 类型化只约束内置 adapter；社区 adapter 的 config 键仍是自由的。
- benchmark 无 data 的路径（占位即最终 sessions）协议校验不变。

## 验证

- `tests/test_config.py`：placeholder 正反例、内置 config 类型化正反例、
  JudgeSpec.prompt ⊆ verifier 注册表。
- `tests/test_dataloader.py`：name 解析（捆绑命中 / 缓存命中 / 未命中报错）。
- `tests/test_memory_instruction.py`：benchmark 配置占位标记后加载 + build 不变。
- 全量 `make test` + `make lint`；`configs/smoke` / `configs/backends` 全部改用
  name/placeholder 后重新 `make smoke-mock` 验证。

## 未完成

- 其余 19 个 benchmark 接入 `DATASET_REGISTRY`（各数据集来源/许可不一，逐个接是社区任务）。
