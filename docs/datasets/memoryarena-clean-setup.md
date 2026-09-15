# MemoryArena：从全新检出目录开始安装

这份 Windows PowerShell 操作步骤不依赖作者已有的代理、虚拟环境、官方源码目录或本地镜像 tag。
前置条件：Git、uv（已验证版本 0.12.13）、运行 Linux 容器的 Docker Desktop、
能够访问固定下载地址的网络，以及可使用指定模型的账号。
请在包含 Issue #4 改动的仓库根目录执行；这些改动尚未发布到上游默认分支。
认证需要运行者本人登录，认证文件、token 和客户端密钥不得放入 Git。

## 创建隔离的框架环境

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

## 独立安装 CLIProxyAPI 并登录

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

## 用固定输入构建 Agent 镜像

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

## 准备官方源码和一条完整任务

```powershell
& $python -m dumemeval prepare --environment-config configs/memoryarena/controlled-math.yaml --clone-reference
if ($LASTEXITCODE -ne 0) { throw 'Official environment preparation failed' }
& $python configs/memoryarena/prepare_assets.py --scene math --output (Join-Path $reproRoot 'assets')
if ($LASTEXITCODE -ne 0) { throw 'Pinned task preparation failed' }
$env:MEMORYARENA_CONTROL_SAMPLE = (Resolve-Path (Join-Path $reproRoot 'assets\math-complete-sample.json')).Path
& $python -m pytest tests/test_memoryarena_cli.py tests/test_memoryarena_search_scoring.py tests/test_scoring_checkpoint.py tests/test_memoryarena_tool_retry.py tests/test_memoryarena_official_parity.py tests/test_memoryarena_judge_retry.py -q
if ($LASTEXITCODE -ne 0) { throw 'Bounded acceptance checks failed' }
```

源码锁定为 `6cd9de14b71915e39ac742a20dc33785e14b6aab`，
数据锁定为 `da1a37c8b19280e18627ca01cf368195a5e1d92e`。
样本选择会生成包含两个问题的完整 Math 第 39 条数据。
`controlled-math.yaml` 使用官方 OpenAI 后端；固定版本的官方 Anthropic 后端
不支持代理返回的 reasoning block 结构。无需修改官方源码。

## 可选：最小真实实验

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
# 完成后只停止本步骤启动的代理进程：
if ($null -ne $proxyProcess) { Stop-Process -Id $proxyProcess.Id }
```

按 [验收记录](memoryarena-acceptance.md) 检查 summary 状态、官方分数和比较警告。
模型输出及记忆使用方式可能变化；取得正向记忆收益不是验收条件。

Travel/Shopping/Search 使用验收记录中的
[可选 worker 与固定资源准备命令](memoryarena-acceptance.md#optional-worker-and-external-assets)。
Java 17 需单独安装，并将 MEMORYARENA_JAVA_HOME 指向实际安装目录。
Shopping 完整商品目录占用较多内存；已有的 1,000 商品通信固定样例
不能证明全目录运行成功，也不能当作全目录官方成绩。
本地未验证原生 Linux 宿主路由和新账号交互登录。
