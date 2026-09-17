# MemoryArena 运行指南

从包含本 PR 的全新检出目录运行。已验证平台为 Windows PowerShell + Docker Desktop Linux 容器，
前置条件为 Git、uv（验证版本 0.12.13）、可用网络和运行者自己的模型账号。
命令均从仓库根目录执行；凭据只写入私有位置或环境变量。
先准备框架、模型端点和官方样本，再选择 Claude Code 或 Hermes 完成最小 on/off。
五场景的完整资源准备与统一入口在后半部分；结果和限制见[验收报告](acceptance.md)。

<a id="install"></a>

## 1. 安装框架

```powershell
$ErrorActionPreference = 'Stop'
$proxyProcess = $null
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$reproRoot = Join-Path (Get-Location) '.cache\memoryarena-repro'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $reproRoot 'venv'
uv python install 3.12.11
uv sync --locked --python 3.12.11 --extra dev --extra harbor --extra judge --extra memoryarena
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
$python = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts\python.exe'
uv pip check --python $python
$env:MEMORYARENA_PYTHON = $python
$env:MEMORYARENA_REFERENCE = Join-Path $reproRoot 'reference'
docker info --format '{{.OSType}}'   # 应输出 linux
```

`.cache/` 已被 Git 忽略。上述步骤安装框架锁定的 122 个包；
Shopping/Search 的可选 worker 使用独立环境，见文末说明。
`memoryarena` 依赖组限制 `anthropic<1`，以兼容固定上游版本传入 `temperature` 的调用。

<a id="proxy"></a>

## 2. 准备模型端点

下面复现已记录的 CLIProxyAPI 路径。可复用自己已有的兼容端点；更换端点或模型时，
同步修改 Agent、官方 worker 和 judge 的配置，并保持 on/off 一致。

固定的 [v7.3.2 发布版](https://github.com/router-for-me/CLIProxyAPI/releases/tag/v7.3.2)
对应提交 `7fa443dc8bf8ca2f1ffd81c2472deb31b097b697`。
代理的 `-codex-login`、`-codex-device-login` 和 `-config` 参数定义见该版本的
[程序入口](https://github.com/router-for-me/CLIProxyAPI/blob/7fa443dc8bf8ca2f1ffd81c2472deb31b097b697/cmd/server/main.go)。
8317 端口必须空闲。如果该端口已有你自己的可用代理，直接复用并导出它的客户端密钥，
不要再启动一个监听进程或停止无关进程。
使用其他端口时，需要同步修改 controlled-math.yaml 中显式配置的 URL。

```powershell
$proxyRoot = Join-Path $env:LOCALAPPDATA ('DuMemEval\memoryarena-repro-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $proxyRoot | Out-Null
$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
icacls $proxyRoot /inheritance:r /grant:r "*${currentSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Private directory ACL setup failed' }
$archive = Join-Path $proxyRoot 'proxy.zip'
Invoke-WebRequest 'https://github.com/router-for-me/CLIProxyAPI/releases/download/v7.3.2/CLIProxyAPI_7.3.2_windows_amd64.zip' -OutFile $archive
if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'a07ada91dcd83f24e491c78ad543a9d08d36d2472408194b21cf9d0a46eb4be1') { throw 'Proxy checksum mismatch' }
Expand-Archive -LiteralPath $archive -DestinationPath $proxyRoot
$proxyExe = Join-Path $proxyRoot 'cli-proxy-api.exe'
$proxyConfig = Join-Path $proxyRoot 'config.yaml'
$proxyAuth = (Join-Path $proxyRoot 'auth').Replace('\', '/')
$keyBytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($keyBytes)
$rng.Dispose()
$env:DUMEMEVAL_PROXY_KEY = [Convert]::ToBase64String($keyBytes)
Set-Content -LiteralPath (Join-Path $proxyRoot 'client-key.txt') -Value $env:DUMEMEVAL_PROXY_KEY -Encoding ascii
@"
host: "127.0.0.1"
port: 8317
auth-dir: "$proxyAuth"
api-keys:
  - "$env:DUMEMEVAL_PROXY_KEY"
debug: false
request-log: false
logging-to-file: false
usage-statistics-enabled: false
request-retry: 0
max-retry-credentials: 1
plugins:
  enabled: false
remote-management:
  allow-remote: false
  secret-key: ""
  disable-control-panel: true
payload:
  override:
    - models:
        - name: "gpt-5.5"
          protocol: "codex"
      params:
        reasoning.effort: medium
"@ | Set-Content -LiteralPath $proxyConfig -Encoding utf8

# 由运行者完成交互式账号登录。
& $proxyExe -config $proxyConfig -codex-login
# 无法自动打开浏览器时，可改用下面的命令：
# & $proxyExe -config $proxyConfig -codex-device-login -no-browser

$proxyProcess = Start-Process -FilePath $proxyExe -ArgumentList @('-config', ('"' + $proxyConfig + '"')) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $proxyRoot 'stdout.log') -RedirectStandardError (Join-Path $proxyRoot 'stderr.log')
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
  if ($proxyProcess.HasExited) { throw 'Proxy exited; inspect its private logs' }
  try {
    $models = Invoke-RestMethod 'http://127.0.0.1:8317/v1/models' -Headers @{Authorization = 'Bearer ' + $env:DUMEMEVAL_PROXY_KEY} -TimeoutSec 2
    if ($models.data.id -contains 'gpt-5.5') { $ready = $true; break }
  } catch { }
  Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'Proxy is not ready or the account does not expose gpt-5.5' }
```

模型目录检查不会调用模型。不能只依据登录命令的退出码判断认证成功：
该版本认证失败时也可能未返回非零退出码。请保留私有日志用于排查，
并确保账号有实际推理所需的额度。
历史运行使用了已有的短期认证；本步骤由运行者独立登录，不复制其他应用的 token。

代理配置关闭了额外重试轮次和切换凭据重试。受管 Math/Phys worker 和框架 judge
也关闭 SDK 重试。复用已有代理时应保留这些设置；
如果外部服务或自定义网关自行重发请求，这种行为不在框架的投递保证范围内。

<a id="sample"></a>

## 3. 准备官方源码和完整样本

```powershell
& $python -m dumemeval prepare --environment-config configs/memoryarena/controlled-math.yaml --clone-reference
if ($LASTEXITCODE -ne 0) { throw 'Official environment preparation failed' }
& $python configs/memoryarena/prepare_assets.py --scene math --output (Join-Path $reproRoot 'assets')
if ($LASTEXITCODE -ne 0) { throw 'Pinned task preparation failed' }
$env:MEMORYARENA_CONTROL_SAMPLE = (Resolve-Path (Join-Path $reproRoot 'assets\math-complete-sample.json')).Path
```

源码锁定为 `6cd9de14b71915e39ac742a20dc33785e14b6aab`，
数据锁定为 `da1a37c8b19280e18627ca01cf368195a5e1d92e`。
样本选择会生成包含两个问题的完整 Math 第 39 条数据。
`controlled-math.yaml` 使用官方 OpenAI 后端；固定版本的官方 Anthropic 后端
不支持代理返回的 reasoning block 结构。无需修改官方源码。

<a id="controlled-runs"></a>

## 4. 执行真实 on/off

### Claude Code

```powershell
$imageContext = Join-Path $reproRoot 'agent-image'
New-Item -ItemType Directory -Path $imageContext -Force | Out-Null
$claude = Join-Path $imageContext 'claude'
Invoke-WebRequest 'https://downloads.claude.ai/claude-code-releases/2.1.89/linux-x64/claude' -OutFile $claude
if ((Get-FileHash $claude -Algorithm SHA256).Hash.ToLowerInvariant() -ne '903cb3c96b314d86856632c8702f5cdf971b804d0b19ef87446573bcd1d7df1c') { throw 'Agent checksum mismatch' }
Copy-Item configs/memoryarena/skills $imageContext -Recurse -Force
Copy-Item configs/memoryarena/agent.Dockerfile (Join-Path $imageContext 'Dockerfile') -Force
$env:MEMORYARENA_CONTROL_IMAGE = 'dumemeval-claude:2.1.89-repro'
docker build --platform linux/amd64 -t $env:MEMORYARENA_CONTROL_IMAGE $imageContext
if ($LASTEXITCODE -ne 0) { throw 'Image build failed' }
$controlImageId = docker image inspect $env:MEMORYARENA_CONTROL_IMAGE --format '{{.Id}}'
docker run --rm $env:MEMORYARENA_CONTROL_IMAGE claude --version
# 检查 Docker 到宿主机的路由：未携带客户端密钥时应返回 401。
docker run --rm $env:MEMORYARENA_CONTROL_IMAGE python -c 'import urllib.request, urllib.error; exec("try:\n urllib.request.urlopen(\"http://host.docker.internal:8317/v1/models\", timeout=5)\nexcept urllib.error.HTTPError as e:\n assert e.code == 401\n print(\"Docker proxy routing OK (401)\")")'
if ($LASTEXITCODE -ne 0) { throw 'Docker proxy routing failed' }
```

此 Dockerfile 直接使用固定的 Python 基础镜像、校验过的 Claude Code 2.1.89
原生二进制和仓库共用的记忆 Skill 构建，无需预先存在本地镜像 tag。
重新构建可能产生不同的镜像 ID，但两组实验必须保持 `$controlImageId` 一致。
这些是可选诊断输入，不涉及项目的 Docker 发布流水线。

以下命令每组调用模型运行两个会话，不遍历完整数据集。
前面的安装和测试可以在不执行模型推理的情况下验证。请使用新的运行名称：

```powershell
$env:MEMORYARENA_CONTROL_RUN = 'controlled-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$env:MEMORYARENA_ARM = 'on'
$env:MEMORYARENA_PROTOCOL = 'memory_session_transfer'
$env:MEMORYARENA_MEMORY_TYPE = 'directory'
& $python -m dumemeval run --config configs/memoryarena/controlled-math.yaml --no-resume
if ($LASTEXITCODE -ne 0) { throw 'On arm failed; inspect its execution status' }
if ((docker image inspect $env:MEMORYARENA_CONTROL_IMAGE --format '{{.Id}}') -ne $controlImageId) { throw 'Image changed between arms' }
$env:MEMORYARENA_ARM = 'off'
$env:MEMORYARENA_PROTOCOL = 'test_only'
$env:MEMORYARENA_MEMORY_TYPE = 'none'
& $python -m dumemeval run --config configs/memoryarena/controlled-math.yaml --no-resume
if ($LASTEXITCODE -ne 0) { throw 'Off arm failed; inspect its execution status' }
$runDir = Join-Path 'results/memoryarena' $env:MEMORYARENA_CONTROL_RUN
& $python -m dumemeval compare (Join-Path $runDir 'off') (Join-Path $runDir 'on') --baseline off --output (Join-Path $runDir 'comparison')
```

按 [验收记录](acceptance.md) 检查 summary 状态、官方分数和比较警告。
模型输出及记忆使用方式可能变化；取得正向记忆收益不是验收条件。

### Hermes（可选）

复用第 1–3 步的变量和样本，无需构建 Claude 镜像。
Harbor 0.22 的安装/version/provider 路由通过 `hermes_repro.py` 在当前进程内兼容；
原生 `Hermes.run` 和轨迹导出保持原样。运行入口检查固定镜像、SDK、共用 Skill 及两组输入的一致性。

#### 构建 Hermes 镜像

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
并拒绝两组之间更换这些输入。历史镜像 ID 见验收附件内的运行清单。

#### 执行完整两轮 Math on/off

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

`hermes-memory-link.yaml` 另提供随机标记诊断；它不是官方样本或官方评分。
其结果、原生读取与记忆快照保存在验收附件中。上述 Math 对照已覆盖真实跨 session 记忆。

<a id="assets"></a>

## 5. 外部 worker 和资源

已测试的 worker 使用 Python 3.10.21、Java 17、CPU Torch 2.2.2、
spaCy 3.7.5 及 `en_core_web_lg` 3.7.1、Pyserini 0.17.0、Transformers 4.51.3。
准确版本见 `configs/memoryarena/worker-requirements.txt`，全部安装在核心框架之外的独立环境中。
Shopping 官方依赖同时固定 spaCy 3.3.0 和 Pydantic 2.5.3，两者无法共同解析；
这里使用的兼容 worker 锁定清单是明确记录的依赖差异，未修改官方源码。

```powershell
$assetsRoot = Join-Path (Get-Location) '.cache\memoryarena-assets'
uv python install 3.10.21
uv venv --python 3.10.21 (Join-Path $assetsRoot 'worker')
$worker = Join-Path $assetsRoot 'worker\Scripts\python.exe'
uv pip install --python $worker --index-url https://download.pytorch.org/whl/cpu 'torch==2.2.2+cpu'
uv pip install --python $worker --no-deps -r configs/memoryarena/worker-requirements.txt
uv pip check --python $worker
$env:MEMORYARENA_PYTHON = $worker
# 先安装 Java 17，再指定实际安装目录。
$env:MEMORYARENA_JAVA_HOME = $env:JAVA_HOME
if (-not $env:MEMORYARENA_JAVA_HOME) { throw 'Set JAVA_HOME to the installed Java 17 directory' }
```

锁定清单中仅限 Windows 的依赖带有平台标记。
不声称已完成原生 Linux 宿主验证；Linux 需要相应调整路径和 Docker 宿主路由。

资源下载到显式指定的输出目录，不纳入源码版本控制。
准备命令包含固定的源码/数据/tokenizer 版本，并生成清单：

```powershell
uv run python configs/memoryarena/prepare_assets.py --scene travel --reference $env:MEMORYARENA_REFERENCE --output $assetsRoot
$env:MEMORYARENA_TRAVEL_DATABASE = Join-Path $assetsRoot 'travel\database'

uv run python configs/memoryarena/prepare_assets.py --scene shopping --output $assetsRoot
$env:MEMORYARENA_PRODUCT_DATA = Join-Path $assetsRoot 'shopping'

uv run python configs/memoryarena/prepare_assets.py --scene search --output $assetsRoot --worker-python $worker --java-home $env:MEMORYARENA_JAVA_HOME
$env:MEMORYARENA_SEARCH_INDEX = Join-Path $assetsRoot 'search-bm25-utf8'
$env:MEMORYARENA_TOKENIZER_CACHE = Join-Path $assetsRoot 'search-tokenizer-cache\hub'
```

Search 准备过程导出固定版本中的全部 100,195 篇语料，并为官方支持的 BM25 searcher
构建本地 Lucene 索引，无需 embedding 模型。
tokenizer 固定在 `c1899de289a04d12100db370d81485cdf75e47ca`，
worker 要求匹配的 `refs/main` 和离线标志。索引与 tokenizer 文件均记录指纹。
Windows Java 必须显式使用 UTF-8：Anserini 可能在解析失败后仍返回退出码 0，
因此准备脚本还会核对文档数量。

这套配置使用 `configs/memoryarena/search-bm25.yaml`。
原始 `search.yaml` 保留官方 OpenAI 稠密检索选项，需要匹配的 embeddings、
索引映射、语料和 embedding 端点。两套配置均不报告 qrel recall。

完成资源准备后，使用下一节的统一准备与运行入口。

Shopping 本地通信验证使用打乱后的前 1,000 个商品、完整官方搜索索引和一个自编购买固定样例，
将内存占用控制在这台 16 GB 机器可承受的范围内。
完整商品文件已下载，仍为默认配置，但未运行全目录评分。
准备相同的可选通信子集时，添加 `--shopping-smoke-limit 1000`，
并在准备脚本的 Python 环境中提供 `ijson==3.4.0`
（例如 `uv run --with ijson==3.4.0 python ...`）。该子集不能作为全目录评测结果。

<a id="five-scenes"></a>

## 6. 五场景统一入口

配置清单见 [configs/memoryarena](../../../configs/memoryarena/README.md)。通用模板使用 Anthropic 兼容服务，
先按自己的服务导出 `MEMORYARENA_AGENT_MODEL`、`MEMORYARENA_JUDGE_MODEL`、`ANTHROPIC_AUTH_TOKEN`、
`ANTHROPIC_BASE_URL`，并确保 URL 同时可被宿主 worker 和 Agent 容器访问。
上面的固定代理实验使用独立的 `controlled-math*.yaml`（官方 OpenAI backend），不把代理 reasoning block 传给旧版官方 Anthropic backend。

```powershell
$scene = 'travel' # 可改为 math、phys、shopping、search-bm25；稠密检索使用 search
foreach ($key in @('MEMORYARENA_AGENT_MODEL', 'MEMORYARENA_JUDGE_MODEL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL')) {
  if (-not [Environment]::GetEnvironmentVariable($key)) { throw "Set $key for your model endpoint" }
}
$config = "configs/memoryarena/$scene.yaml"
$env:MEMORYARENA_ARM = 'on'
$env:MEMORYARENA_PROTOCOL = 'memory_session_transfer'
$env:MEMORYARENA_MEMORY_TYPE = 'directory'
& $python -m dumemeval prepare --environment-config $config
if ($LASTEXITCODE -ne 0) { throw 'Environment preparation failed' }
& $python -m dumemeval run --config $config --no-resume
if ($LASTEXITCODE -ne 0) { throw 'Run failed; inspect its artifacts' }
```

每个通用模板默认选择一条完整源数据。通用 on/off 会额外改变记忆指令后缀；提示词完全相同的受控实验使用第 4 节。
新实验应使用新的输出目录；`--no-resume` 不会删除评分检查点。
`prepare` 核验官方 revision、资源和实际 worker SDK，成功不等于模型认证或 Docker 已就绪。
Math/Phys 所选 backend 还需要对应 SDK：OpenAI/OpenRouter 为 openai，Anthropic 为 anthropic，Gemini/Google 为 google-genai。

<a id="checks"></a>

## 7. 本地检查和产物

设置 `MEMORYARENA_REFERENCE` 后运行；官方 HTTP 测试使用真实本地服务和确定性 judge，不调用付费模型。
没有官方源码或可选依赖时会跳过相应检查，不能据此声称 parity 通过。
仓库与 GitHub 的统一门禁为 `make ci`（含打包、示例及四臂 mock smoke）；下面列出 PowerShell 检查命令。

```powershell
& $python -m pytest tests/benchmarks/memoryarena tests/test_environment_extensions.py tests/test_experiment_controls.py tests/test_control_completeness.py tests/test_memory_observation.py tests/test_scoring_checkpoint.py tests/test_verifier_clients.py -q
& $python -m ruff check src tests
& $python -m ruff format --check src tests
# Windows 的 3 项平台断言差异及新上游复现结果见验收报告。
& $python -m pytest tests -m 'not e2e' -q
& $python -m mypy
uv build --python $python --out-dir .cache/memoryarena-dist
git diff --check
```

| 产物 | 核验内容 |
| --- | --- |
| `experiment_config.json` | 脱敏配置、git/源码/数据/依赖及控制指纹 |
| `environments/<task>/` | `preparation.json`、`runtime.json`、`trace.json`、服务日志：资源、readiness/reset/动作/关闭及诊断 |
| `trials/<task-session>/agent/` | Harbor 原生与 ATIF 轨迹、独立会话身份和实际工具调用 |
| `snapshots/`、`scoring/` | 跨会话记忆快照、评分检查点 |
| `result.json` / `report.md`、`summary.json` / `summary.md` | 分离的执行状态、官方评分、judge 和派生指标 |
| comparison JSON / Markdown | 样本、控制变量差异和缺失证据警告 |

运行结束自动回收自有官方服务、会话权限和容器。所有实验结束后，仅停止本指南启动的代理：

```powershell
if ($null -ne $proxyProcess -and -not $proxyProcess.HasExited) { Stop-Process -Id $proxyProcess.Id }
```

<a id="troubleshooting"></a>

## 8. 故障排查

| 现象 | 检查与处理 |
| --- | --- |
| prepare 非零退出 | 查看缺失文件/SDK；检查固定 revision、worker Python、Java 17 和资源路径。不要把 `ready` 当成 API 调用成功。 |
| 401 或模型不存在 | 检查本人的代理登录、模型目录和凭据；Hermes 使用兼容入口显式选择 `openai-api`。失败运行保留为失败/未测。 |
| 容器访问不到宿主 | Docker Desktop 使用 `host.docker.internal`；原生 Linux 需配置路由与 `agent_host`，尚未验证该宿主平台。 |
| 工具响应丢失 | 重试同一命令/请求 ID，保留客户端待处理身份；不要把结果不明的写操作当作新动作重放。 |
| 评分检查点未完成或损坏 | 检查原尝试；确认重做时使用新输出目录，框架不自动再次调用 judge。 |
| comparison 报缺少指纹 | 旧报告不具备新增字段；保持原始分数，将自动可比性标为未验证，不补造证据。 |
| token/cost 为零 | Hermes 的 Harbor ATIF 缺少会话级用量；查原生统计，费用未知，不把零解释为免费调用。 |

验证限于已记录的 Windows 环境、最小真实 Math 实验和官方固定样例；未执行五场景全量评测、原生 Linux 宿主或新账号交互登录。
