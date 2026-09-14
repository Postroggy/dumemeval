# 数据准备与捆绑 smoke 子集

- 状态：implemented
- 源码：`src/dumemeval/datasets/prepare.py` · `src/dumemeval/cli/prepare.py` · `data/smoke/`
- 配置：`configs/smoke/`（内置子集）· `configs/backends/`（完整数据走缓存）

## 问题

框架不附带官方数据集（体积 + 上游许可），smoke 真跑此前要求使用者：
1. 自己下载 LoCoMo / MemoryArena 官方数据
2. 手动改 yaml 里的 `../../Dataset/...` 本机路径
3. 自己拆「有记忆语义的 smoke 子集」（不知道 evidence↔session 映射就拆不对）

「第一次就能卡住」的最大点就是数据准备——文档只说了路径是维护者本机的，没有一条
「下载到哪、改哪一行」的最短清单。改动前 `src/dumemeval/datasets/prepare.py`
已经写了下载与切片逻辑，但没有 CLI 入口，配置也没指向它，等于没接线。

## 方案

三层数据获取，越往下越重：

| 层 | 数据 | 获取 | 适用 |
|---|---|---|---|
| 零下载 | `data/smoke/`（官方子集，随仓库捆绑） | clone 即得 | `configs/smoke/` 真跑对照、CI |
| 一键下载 | 完整官方数据 → `~/.cache/dumemeval/datasets` | `dumemeval prepare`（或 `make prepare`） | `configs/backends/` 全量实验 |
| 自备 | 任意本地目录 | 设 `DUMEMEVAL_DATA_DIR` | 已有数据集/离线环境 |

### 捆绑子集（`data/smoke/`）

- `locomo_smoke.json`：官方 `locomo10.json` 对话 `conv-26` 的 `session_1..4` +
  evidence 落在其内的 5 题（5 类别 × 各 1 题，含 cat5 对抗题）——真实 memory 语义，
  零下载可出官方口径 F1。
- `shopping_smoke.jsonl`：bundled_shopping 第 0 个样本前 2 回合（跨回合记忆约束）。
- 生成口径与 `prepare.py` 的 `slice_locomo_smoke(n_sessions=4, per_category=1)` /
  `slice_shopping_smoke(n_rounds=2)` 完全一致——`dumemeval prepare` 可重新生成，
  捆绑文件 = prepare 产物，两处不同步由 `tests/test_prepare.py` 的
  `TestBundledSmokeFiles` 兜底。
- 许可：LoCoMo 为 CC BY-NC 4.0（Adapted Material 按同一许可分发，署名见
  `data/smoke/README.md` 与 `NOTICE`）；MemoryArena 见 HF 页。子集只用于验证链路，
  分数不可引用（GOVERNANCE「勿过度解读」同语义）。

### 完整数据（`dumemeval prepare`）

```bash
dumemeval prepare                  # locomo + shopping（缓存命中即跳过）
dumemeval prepare --dataset locomo # 只要 locomo
dumemeval prepare --force          # 强制重新下载
```

- 缓存根：`~/.cache/dumemeval/datasets`（`DUMEMEVAL_DATA_DIR` 可覆盖，prepare.py 已支持）。
- 配置侧统一用**逻辑数据名** `data.name`（`locomo_smoke` / `shopping_smoke` / `locomo` /
  `bundled_shopping`），框架按 仓库捆绑 `data/smoke/` → prepare 缓存 自动解析
  （`datasets/prepare.py` 的 `DATASET_REGISTRY` + `resolve_dataset`），配置里不再出现路径。
- shopping 的 webshop 商品库/env server 仍是使用者的责任（`cmd_prepare` 会显式警告）。

## 备选方案与否决理由

| 方案 | 否决理由 |
|---|---|
| 把完整官方数据打进 git | 体积（locomo10 2.7MB、bundled_shopping 1.5MB 起）+ 上游许可不允许再分发 |
| 继续让用户手改 yaml 路径 | 正是要消除的摩擦；env 模板 + 内置子集让 smoke 路径零改动 |
| prepare 改写 git 里的 yaml（`rewrite_smoke_paths`） | 改被跟踪文件 = 每个克隆都脏；smoke 内置后无需再改（已删除该函数） |
| `datasets.loader` 直接支持 `hf` 源、配置写 HF id | 需要 `datasets` 包 + 网络 + 每次构建拉取；缓存下载仍是最稳路径，loader 的 hf/git 源保留给有版本锁定需求的用户 |

## 语义边界

- 捆绑子集分数不可引用，只证明「真跑链路能出官方口径」。
- shopping 官方 ASIN 分依赖 webshop env server 存活；prepare 只给任务文件，不保证官方分非 0。

## 验证

- `tests/test_prepare.py`：切片逻辑（离线）、捆绑文件与切片口径一致、CLI 接线（monkeypatch 下载）。
- `tests/test_memory_instruction.py`：smoke 配置用捆绑数据 load + build，不再依赖本机 `Dataset/`。
- CI 新增一步：`configs/smoke/locomo_transfer.yaml --mock`（零下载、零 Docker 验证捆绑数据可跑）。
- `dumemeval prepare` 按 DatasetSpec registry 准备已注册数据；不再依赖 doctor 命令。

## 未完成

- 其他 19 个 benchmark 的官方数据没有一键下载（各数据集来源/许可不一，逐个接 prepare 是社区任务）。
- shopping 的 webshop 商品库与 env server 一键拉起（官方 `setup_web_shopping.md` 是手工流程）。
