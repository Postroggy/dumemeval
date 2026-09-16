# Hermes 复跑：功能验收与复现材料

Hermes 的真实运行、官方工具调用和跨会话目录记忆均已跑通。本次用于验证功能链路，
没有运行完整评测集，也不要求证明记忆带来分数提升。

## 已完成的真实运行

| 组合 | 完成会话 | 官方 Math paper passrate |
| --- | ---: | ---: |
| Hermes 0.21.3 × directory × CLIProxyAPI → GPT-5.5（medium） | 2/2 | 1.0 |
| Hermes 0.21.3 × none × CLIProxyAPI → GPT-5.5（medium） | 2/2 | 1.0 |

使用与 Claude Code 验收相同的完整 Math 第 39 条数据（paper `2507.18621`），包含两个问题。
样本 SHA-256 为 `82a430425b49471c68a8fc8a00caffe4fd505678fb8001f785abd565a5c3b868`。
两组均 `mock=false`，实际任务提示词逐字相同，9 项历史控制指纹相同。
4 个原生会话 ID 不同，均无父会话，系统提示词哈希一致。
每组都有两次真实 `reasoning` 和两次 `submit`，环境只初始化/重置一次，结束后关闭自有服务及容器。

directory 组首轮写入笔记，第二轮的 `read_file` 返回全文与首轮快照一致，
读取发生在官方推理前，之后再次更新笔记；none 组没有记忆挂载或读写。
原生工具调用数分别为 12 和 7。两组的 Hermes 内置 memory 和 user profile 均关闭。

### 随机标记诊断

另用相同运行时、模型接口和框架记忆适配器执行一个功能诊断。
宿主随机生成 128-bit 标记，只告诉第一会话；第二会话使用新容器，题面及生成文件中没有该标记。

| 组别 | 第二会话返回 | 宿主精确字符串比较 |
| --- | --- | ---: |
| directory | `3fb1f69824df7842e984b1617298c879` | 找回，1/1 |
| none | `UNKNOWN` | 未找回，0/1 |

两组均完成 2/2 个会话；记忆组读取内容与第一份文件快照一致。
这是自行设计的通道检查，**不是官方 MemoryArena 样本或官方指标**。
另直接调用实际官方 Math judge：正确参考答案得到 yes，明显错误答案得到 no。
这两次正反例结果与原 Math 评分分开保存。

原 Math 分差为 0 的原因见证据包的 `diagnostic/diagnosis.md`：
第二题已提供关键背景，none 组仅用当前题面与推理工具就能答对。
官方推理调用没有携带上一轮的对话历史。

## 版本与兼容范围

| 项目 | 固定版本 |
| --- | --- |
| 历史运行的 DuMemEval 提交 | `909e185d043d04db1b5c21df1b610eef52fa0c1c` |
| Harbor | 0.22.0 |
| Hermes | 0.21.3，官方提交 `345cd2b057a452236de401d3534b8502a7465e8d`，tag `v2026.9.14` |
| CLIProxyAPI | 7.3.2；`request-retry: 0`、`max-retry-credentials: 1` |
| MemoryArena 源码 | `6cd9de14b71915e39ac742a20dc33785e14b6aab` |
| MemoryArena 数据 | `da1a37c8b19280e18627ca01cf368195a5e1d92e` |

Hermes 通过显式 `--provider openai-api` 连接代理，在这次配置中选择 `codex_responses`。
Agent 容器访问 `http://host.docker.internal:8317/v1`，宿主的官方推理/judge 访问
`http://127.0.0.1:8317/v1`，模型均为 `gpt-5.5(medium)`。

Harbor 0.22 的 Hermes 安装器没有固定安装脚本，并使用无效的 `hermes version`；
默认 OpenAI 路由没有显式指定 provider。因此，复现入口仅在当前 Python 进程内：

1. 用预装镜像及版本检查代替动态安装。
2. 改用 `hermes --version`。
3. 将原生 OpenAI 路由设为 `openai-api`，转发运行者提供的 key/base URL。

`Hermes.run` 和原生会话/ATIF 导出逻辑保持原样，不修改已安装的 Harbor 文件。
共用的记忆技能直接放入 `/tmp/hermes/skills`，省略 `agent.skills_dir`，
避免 Windows 将容器路径解释为宿主路径。
首次 `provider=auto` 尝试因 HTTP 401 失败，0/2 完成、官方评分未测；失败摘要和日志也保留在证据包中。

## 从全新检出目录复现

在仓库根目录执行。先完成[从零安装指南](clean-setup.md)中的：
“创建隔离的框架环境”“独立安装 CLIProxyAPI 并登录”“准备官方源码和一条完整任务”。
沿用其中的 `$python`、`$reproRoot`、`DUMEMEVAL_PROXY_KEY`、`MEMORYARENA_REFERENCE`、
`MEMORYARENA_PYTHON`、`MEMORYARENA_CONTROL_SAMPLE`；Hermes 镜像按以下步骤构建。
无需构建 Claude 镜像。仅验证功能时，两组各执行一次即可。

### 构建 Hermes 镜像

```powershell
$hermesRoot = Join-Path $reproRoot 'hermes'
$hermesSource = Join-Path $hermesRoot 'source'
$hermesContext = Join-Path $hermesRoot 'image'
$hermesCommit = '345cd2b057a452236de401d3534b8502a7465e8d'
New-Item -ItemType Directory -Path $hermesContext -Force | Out-Null
git clone --branch v2026.9.14 --depth 1 https://github.com/NousResearch/hermes-agent.git $hermesSource
if ($LASTEXITCODE -ne 0) { throw 'Hermes clone failed' }
if ((git -C $hermesSource rev-parse HEAD) -ne $hermesCommit) { throw 'Hermes revision mismatch' }
# --output preserves binary tar bytes on Windows PowerShell.
$hermesTar = Join-Path $hermesContext 'hermes-source.tar'
git -C $hermesSource archive --format=tar --output $hermesTar $hermesCommit
if ($LASTEXITCODE -ne 0) { throw 'Hermes archive failed' }
Copy-Item configs/memoryarena/skills $hermesContext -Recurse -Force
$env:MEMORYARENA_HERMES_IMAGE = 'dumemeval-hermes:0.21.3-repro'
docker build --platform linux/amd64 -f configs/memoryarena/hermes.Dockerfile -t $env:MEMORYARENA_HERMES_IMAGE $hermesContext
if ($LASTEXITCODE -ne 0) { throw 'Hermes image build failed' }
& $python configs/memoryarena/hermes_repro.py --check-only
if ($LASTEXITCODE -ne 0) { throw 'Hermes image/SDK/skill verification failed' }
```

该检查不访问模型，容器禁用网络。构建使用固定源码、uv/Python 镜像和官方 `uv.lock`；
APT 仓库仍随时间变化，重建得到的镜像 ID 可能不同。复现入口保存实际镜像 ID、SDK 版本及自身哈希，
并拒绝两组之间更换这些输入。历史镜像 ID 见校验 JSON。

### 执行完整两轮 Math on/off

```powershell
$env:MEMORYARENA_CONTROL_RUN = 'hermes-controlled-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$env:MEMORYARENA_ARM = 'on'
$env:MEMORYARENA_PROTOCOL = 'memory_session_transfer'
$env:MEMORYARENA_MEMORY_TYPE = 'directory'
& $python -m dumemeval prepare --environment-config configs/memoryarena/controlled-math-hermes.yaml
if ($LASTEXITCODE -ne 0) { throw 'Official environment preparation failed' }
& $python configs/memoryarena/hermes_repro.py
if ($LASTEXITCODE -ne 0) { throw 'Hermes on run failed; preserve this attempt' }

$env:MEMORYARENA_ARM = 'off'
$env:MEMORYARENA_PROTOCOL = 'test_only'
$env:MEMORYARENA_MEMORY_TYPE = 'none'
& $python configs/memoryarena/hermes_repro.py
if ($LASTEXITCODE -ne 0) { throw 'Hermes off run failed; preserve this attempt' }
& $python -m dumemeval compare "results/memoryarena/$env:MEMORYARENA_CONTROL_RUN/off" "results/memoryarena/$env:MEMORYARENA_CONTROL_RUN/on" --baseline off --output "results/memoryarena/$env:MEMORYARENA_CONTROL_RUN/comparison"
```

每次新尝试使用新名称，失败产物也保留。普通 `dumemeval run` 不会自动启用这个特定版本的兼容入口。
以上已验证平台为 Windows + Docker Desktop Linux 容器；原生 Linux 宿主路由仍需另行配置。

### 可选：重新验证随机标记通道

```powershell
$env:MEMORYARENA_CONTROL_RUN = 'hermes-memory-link-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$env:MEMORYARENA_MARKER = & $python -c 'import secrets; print(secrets.token_hex(16))'
foreach ($arm in @('on', 'off')) {
  $env:MEMORYARENA_ARM = $arm
  $env:MEMORYARENA_PROTOCOL = if ($arm -eq 'on') { 'memory_session_transfer' } else { 'test_only' }
  $env:MEMORYARENA_MEMORY_TYPE = if ($arm -eq 'on') { 'directory' } else { 'none' }
  $env:MEMORYARENA_MEMORY_INJECT = if ($arm -eq 'on') { 'true' } else { 'false' }
  & $python configs/memoryarena/hermes_repro.py --config configs/memoryarena/hermes-memory-link.yaml
  if ($LASTEXITCODE -ne 0) { throw 'Diagnostic execution failed; preserve this attempt' }
  $checkpoint = Get-Content "results/diagnostics/$env:MEMORYARENA_CONTROL_RUN/$arm/checkpoints/memory_link_diagnostic.json" -Raw | ConvertFrom-Json
  if ($checkpoint.sessions.Count -ne 2 -or @($checkpoint.sessions | Where-Object { -not $_.success }).Count -ne 0) { throw 'Diagnostic execution incomplete' }
  $answer = $checkpoint.sessions[1].observation.Trim()
  $expected = if ($arm -eq 'on') { $env:MEMORYARENA_MARKER } else { 'UNKNOWN' }
  [pscustomobject]@{arm=$arm; answer=$answer; exactRecall=($answer -ceq $env:MEMORYARENA_MARKER)}
  if ($answer -cne $expected) { throw 'Memory channel control did not match' }
}
```

分数来自上述精确比较，不能使用通用 `summary.json` 的 utility 分数替代。
还应核对第二轮原生 `read_file` 与首轮快照、独立会话 ID，以及 off 组无记忆挂载。

## 证据与统计边界

- [脱敏证据包](hermes-evidence.zip)：Math 86 份原记录、诊断 74 份原记录、两份原哈希清单、实际题面及首次失败摘录。原文件字节和哈希保持不变。
- [校验清单及可读摘要](hermes-verification.json)：包哈希、成员哈希、版本、结果和证据位置。
- 历史脚本及报告包含当时的本机路径和“尚未提交”状态，作为原始记录保留。当前复现使用本文提供的可移植入口。
- 真实模型轨迹对应 `909e185`，不冒充本次提示词指纹/依赖预检修复后的新运行；本次修复另有[回归记录](acceptance-fixes.md#提交前补充修复2026-09-16)。
- 框架自动记忆读取计数目前只识别 Claude `Read`；Hermes 读取以原生 `read_file` 与快照为证。
- Harbor 0.22 的 ATIF 转换未导入 Hermes 会话级 token 统计。框架汇总中的 token/cost=0 应解释为未测量；原生 token 计数保存在证据中，费用未知。
- 单个 Math 样本和一个随机标记诊断能验证运行链路，不能用于跨 runtime 排名或统计性能结论。
