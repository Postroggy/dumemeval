"""实验配置模型（pydantic 全面约束，五段式）。

设计要点：
- 配置加载即校验：ExperimentConfig 是完整配置的 pydantic 模型
- 五段式：experiment / agent / memory / task / execution（+ judging / dataset / output）
- 敏感信息不落盘：用 ${ENV_VAR} 模板引用（Harbor env template）
- protocol 是顶层概念：决定 session 序列如何编排 memory 生命周期
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import TaskEnvSpec, VerifierSpec
from .protocol import EvalProtocol as EvalProtocolABC
from .protocol import protocol_names

if TYPE_CHECKING:
    from ..models import EvalTask

# ── 各段配置模型 ────────────────────────────────────────────────────────────


class ExperimentSpec(BaseModel):
    """实验元信息。"""

    name: str = Field(description="实验名（结果目录用）")
    description: str = ""
    protocol: str = Field(
        default="memory_session_transfer",
        description="评测协议名（注册表：memory_session_transfer / test_only / …；社区可 register_protocol）",
    )
    version: str = Field(default="0.1.0", description="实验版本（结果隔离）")


class AgentSpec(BaseModel):
    """Agent 配置（跑实验的 agent）。"""

    # 开放命名：任意 Harbor 已安装 agent（claude-code/hermes/goose/...），
    # 未知名由 Harbor AgentFactory 报错（不在此白名单，避免加 agent 改 core）
    runtime: str = Field(default="claude-code")
    model: str | None = Field(
        default=None,
        description="agent 模型；None = 由执行引擎 / Harbor 决定。框架不预设厂商模型",
    )
    setup_timeout_sec: float = Field(default=900.0, ge=0)
    temperature: float | None = Field(
        default=None, ge=0, le=2, description="采样温度；None = 不覆盖执行引擎默认"
    )
    max_tokens: int | None = Field(default=None, ge=1, description="单次生成上限；None = 不覆盖执行引擎默认")
    skills_dir: str | None = Field(
        default=None, description="Harbor 原生 Skill 目录；由 Agent runtime 负责加载"
    )


class HermesBuiltinConfig(BaseModel):
    """Hermes 官方内置 memory 的 config 键（未知键在加载期报错，不拖到 adapter 运行期）。"""

    model_config = ConfigDict(extra="forbid")

    targets: list[Literal["memory", "user"]] = Field(
        default_factory=lambda: _DEFAULT_HERMES_TARGETS,
        description="启用哪些文件（MEMORY.md / USER.md）",
    )
    memory_limit: int = Field(default=2200, ge=1, description="MEMORY.md 字符上限")
    user_limit: int = Field(default=1375, ge=1, description="USER.md 字符上限")
    model: str | None = Field(default=None, description="模型名（inject 需要）")
    base_url: str | None = Field(default=None, description="模型 API base（缺省走 MODEL_BASE_URL）")
    api_key: str | None = Field(default=None, description="模型 API key（缺省走 MODEL_API_KEY）")


class EverOSConfig(BaseModel):
    """EverOS 官方 memory 的 config 键（未知键在加载期报错）。"""

    model_config = ConfigDict(extra="forbid")

    app_id: str = Field(default="locomo_benchmark", description="官方默认 app_id")
    project_id: str = Field(default="", description="空 = 每次评测生成唯一命名空间（隔离）")
    method: Literal["agentic", "hybrid", "vector", "keyword"] = Field(
        default="agentic", description="检索方法（官方 config.toml 默认 agentic）"
    )
    top_k: int = Field(default=10, ge=1, description="每题检索 episodes 数")
    batch_size: int = Field(default=25, ge=1, description="/add 每批消息数（官方 25）")
    ready_wait_sec: float = Field(
        default=0.0, ge=0, description="inject 前轮询 search 就绪的秒数（0 不等待）"
    )


# 内置 adapter 的 config 类型化注册表；社区 adapter 不在表内 → config 保持开放 dict
_MEMORY_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "hermes_builtin": HermesBuiltinConfig,
    "everos": EverOSConfig,
}

_DEFAULT_HERMES_TARGETS: list[Literal["memory", "user"]] = ["memory", "user"]


class MemoryBackendSpec(BaseModel):
    """Memory 后端配置（被测对象，一等公民）。

    ``type`` 表达的是**框架接入的外部第三方 memory 系统**（directory / http /
    hermes_builtin / everos / none）。``none`` = 框架不接入任何外部 memory
    （不注入、不观测）——但 agent runtime 自身（hermes / Claude Code 等）是否
    带原生 memory 是 runtime 的属性，与 ``type`` 无关。
    """

    name: str = Field(description="后端名（registry 用）")
    type: str = Field(
        default="directory",
        description="adapter 类型（框架接入的外部 memory 系统；none = 不接入，见 adapters/registry.py）",
    )
    path: str | None = Field(default=None, description="directory/hermes_builtin 型：memory 目录路径")
    base_url: str | None = Field(default=None, description="http 型：服务地址")
    user_id: str | None = Field(default=None, description="隔离键")
    team_id: str = Field(default="default", description="(预留) 租户隔离 team_id")
    agent_id: str = Field(default="default", description="(预留) agent 标识")
    config: dict[str, Any] = Field(default_factory=dict, description="后端特定配置")

    @model_validator(mode="after")
    def _validate_typed_config(self) -> MemoryBackendSpec:
        """内置 adapter 的 config 用类型化模型校验（未知键/类型错 → 加载期报错）。"""
        schema = _MEMORY_CONFIG_MODELS.get(self.type)
        if schema is not None:
            schema.model_validate(self.config)
        return self


class SessionConfig(BaseModel):
    """session 定义（配置版）。"""

    instruction: str = Field(description="给 agent 的任务指令")
    verifier: VerifierSpec | None = Field(default=None, description="该 session 的判分配置")
    memory_inject: bool = Field(default=True, description="是否注入 memory")
    placeholder: bool = Field(
        default=False,
        description=(
            "是否为占位 session：benchmark + data 路径下真实 sessions 由适配器 "
            "build_tasks 生成，配置里的 sessions 只是占位（指令会被覆盖）——"
            "必须显式标 placeholder=true，防止误改占位指令。非 benchmark 路径 "
            "禁止 placeholder=true。"
        ),
    )
    artifacts: list[str] = Field(default_factory=list, description="需要收集的产出文件")
    env_extra: dict[str, str] = Field(default_factory=dict, description="环境附加配置")


class DatasetSpec(BaseModel):
    """数据源配置。

    三种来源：local（本地路径/逻辑名）/ hf（HuggingFace）/ git（repo+commit）。
    ``name`` 是逻辑数据名（locomo_smoke / shopping_smoke / locomo /
    bundled_shopping），按 仓库捆绑 data/smoke → prepare 缓存 顺序解析——
    用户写「要哪个数据集」，框架负责找文件（见 datasets/prepare.py 的
    DATASET_REGISTRY）。自备数据仍用显式 ``path``。
    """

    type: Literal["local", "hf", "git"] = Field(default="local")
    name: str | None = Field(
        default=None,
        description="逻辑数据名（内置：locomo_smoke / shopping_smoke / locomo / bundled_shopping）；type=local 且 path 为空时按此解析",
    )
    path: str | None = None
    dataset: str | None = None
    config: str | None = None
    split: str = Field(default="test")
    revision: str | None = None
    repo: str | None = None
    commit: str | None = None


class TaskSpec(BaseModel):
    """任务配置（multi-session）。"""

    sessions: list[SessionConfig] = Field(min_length=1, description="session 序列（后者依赖前者）")
    memory_ground_truth: str = Field(default="", description="Quality 判分标准")
    task_ground_truth: str = Field(default="", description="Utility 判分标准")
    data: DatasetSpec | None = Field(default=None, description="任务数据源")
    benchmark: str | None = Field(default=None, description="数据集指标计算器（locomo / memoryarena_travel）")
    benchmark_options: dict[str, Any] = Field(
        default_factory=dict, description="benchmark 适配器参数（subset / max_questions 等）"
    )
    judgement_mode: Literal["hint", "answer", "none"] | None = Field(
        default=None, description="MemoryArena 官方 judgement_mode"
    )
    memory_instruction: Literal["none", "location", "proactive"] = Field(
        default="none",
        description=(
            "是否告知 agent 持久记忆的存在：none=原文（基线）；location=告知位置；"
            "proactive=告知位置并要求主动读写。memory 的使用是 agent 的决策，"
            "不告知则测不了这个决策（见 docs/lifecycle/memory-instruction-modes.md）"
        ),
    )
    task_environment: TaskEnvSpec | None = Field(
        default=None, description="agentic 任务环境（webshop 等 env server）；None = 纯文本任务"
    )

    @model_validator(mode="after")
    def validate_placeholder_semantics(self) -> TaskSpec:
        """sessions 占位语义：benchmark + data 必须显式标 placeholder；非 benchmark 禁止。

        benchmark + data 路径下真实 sessions 由适配器 build_tasks 生成，配置里的
        sessions 只是占位（指令会被覆盖）——必须显式标 placeholder=true，防止用户
        误改占位指令却静默不生效。非 benchmark 路径没有适配器，placeholder 无意义。
        """
        is_benchmark = bool(self.benchmark and self.data is not None)
        for session in self.sessions:
            if is_benchmark and not session.placeholder:
                raise ValueError(
                    "benchmark + data 路径下 sessions 是占位（真实 sessions 由适配器 "
                    "build_tasks 生成，指令会被覆盖）——必须给每个 session 标 "
                    "placeholder: true"
                )
            if not is_benchmark and session.placeholder:
                raise ValueError(
                    "placeholder: true 只用于 benchmark + data 路径（没有适配器生成 sessions，占位无意义）"
                )
        return self


class JudgeSpec(BaseModel):
    """判分配置（主路径：LLM as judge；rule 用于测试/结构化场景）。

    ``prompt`` 是 Quality / 非 benchmark 判分默认模板；benchmark 路径下各
    calculator 用自己的口径 prompt 覆盖（透传只带 model/key/多数票等字段，
    见 verifier/llm.py 的 ``make_llm_judge``）。模板集合与
    ``LLMJudgeVerifier._PROMPT_TEMPLATES`` 对齐，由测试锁定同步。
    """

    type: Literal["llm_judge", "rule"] = Field(default="llm_judge")
    prompt: Literal["memory_qa", "memory_quality", "task_success", "math_equivalence", "search_grader"] = (
        Field(default="memory_quality")
    )
    model: str | None = None
    base_url: str | None = None
    api_key_env: str = Field(
        default="ANTHROPIC_AUTH_TOKEN", description="Judge API key 环境变量；默认复用 Claude/Anthropic 配置"
    )
    max_tokens: int = Field(default=1024, ge=1)
    temperature: float = Field(default=0.0, ge=0, le=2)
    num_runs: int = Field(default=1, ge=1, description="LLM-as-Judge 重复次数（多数票 + 分数均值）")
    max_retries: int = Field(default=3, ge=0, description="瞬时错误最多尝试次数（含首次；0 视为 1）")
    skip_failed: bool = Field(default=False, description="judge 失败时记 SKIPPED 而非中断")
    save_model_input: bool = Field(default=False, description="把 judge user prompt 写入 Verdict.model_input")


class EnvironmentSpec(BaseModel):
    """隔离环境配置（映射到 Harbor 的 environment 配置）。

    默认生成**最小镜像**（不改镜像源、不预装任何 agent——agent 安装是 Harbor
    的职责）。地域优化 / 预装依赖 / 整份 Dockerfile 均为用户显式配置。
    """

    type: Literal["docker"] = Field(default="docker")
    force_build: bool = Field(default=True)
    docker_image: str | None = Field(
        default=None,
        description="预构建镜像（作为 base_image 使用；含 hermes 等已装好的镜像）",
    )
    base_image: str = Field(default="python:3.13-slim", description="生成的 Dockerfile 的 FROM")
    apt_mirror: str | None = Field(
        default=None, description="Debian apt 镜像域名（如 mirrors.tuna.tsinghua.edu.cn）；None 不改源"
    )
    pip_index_url: str | None = Field(default=None, description="pip index；None 用官方源")
    apt_packages: list[str] = Field(default_factory=list, description="构建期额外 apt 包")
    pip_packages: list[str] = Field(default_factory=list, description="构建期额外 pip 包")
    setup_commands: list[str] = Field(
        default_factory=list, description="构建期任意命令（预装 agent CLI 等），按序执行"
    )
    dockerfile: str | None = Field(
        default=None, description="整份 Dockerfile 文件路径；设置后完全接管，忽略以上构建字段"
    )
    # task.toml 资源
    agent_timeout_sec: float = Field(default=5400.0, ge=1, description="agent 单 session 超时")
    cpus: int = Field(default=1, ge=1)
    memory_mb: int = Field(default=2048, ge=128)
    storage_mb: int = Field(default=10240, ge=128)
    env: dict[str, str] = Field(default_factory=dict, description="env 模板（${VAR} 引用宿主）")
    mounts: list[MountSpec] = Field(default_factory=list)


class MountSpec(BaseModel):
    """目录挂载配置（映射到 Harbor 的 volume 配置）。"""

    type: Literal["bind"] = Field(default="bind")
    source: str = Field(description="host 路径")
    target: str = Field(description="容器内路径")


class ExecutionSpec(BaseModel):
    """执行层配置。"""

    engine: Literal["harbor", "mock"] = Field(default="mock")
    trials: int = Field(
        default=1,
        ge=1,
        description="重复次数（预留：执行层尚未实现多次 attempts 统计，当前恒跑 1 次）",
    )
    n_concurrent: int = Field(
        default=1,
        ge=1,
        description="跨 task 并行度（task 内 session 因 memory 依赖恒串行）",
    )
    resume: bool = Field(
        default=True,
        description="跳过 output_dir/checkpoints 里已完成的 task（--no-resume 关闭）",
    )
    environment: EnvironmentSpec = Field(default_factory=EnvironmentSpec)


class OutputSpec(BaseModel):
    """输出配置。"""

    dir: str = Field(default="results")
    tasks_dir: str = Field(default="tasks_generated")
    format: Literal["json", "md", "json+md"] = Field(default="json+md")


# ── 完整配置 ────────────────────────────────────────────────────────────────


class ExperimentConfig(BaseModel):
    """一次实验的完整配置（配置加载的唯一入口，pydantic 强校验）。"""

    experiment: ExperimentSpec
    agent: AgentSpec = Field(default_factory=AgentSpec)
    memory: MemoryBackendSpec
    task: TaskSpec
    judging: JudgeSpec = Field(default_factory=JudgeSpec)
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)
    output: OutputSpec = Field(default_factory=OutputSpec)

    @model_validator(mode="after")
    def validate_protocol_sessions(self) -> ExperimentConfig:
        """协议与 session 序列的交叉校验（委托给协议对象）。

        benchmark 路径（benchmark + data 齐备）的 sessions 是占位——真实 sessions
        由适配器 build_tasks 生成，cli._build_tasks 会对产物做协议归一化 + 逐任务
        校验（本框架唯一执行入口），跳过占位校验；benchmark 缺 data 时占位即最终
        sessions，仍走此校验。
        """
        if self.task.benchmark and self.task.data:
            return self
        self.protocol_instance.validate(
            n_sessions=len(self.task.sessions),
            memory_injects=[s.memory_inject for s in self.task.sessions],
        )
        return self

    @property
    def protocol_instance(self) -> EvalProtocolABC:
        """协议对象（运行时解析，校验逻辑在协议类里）。"""
        from .protocol import get_protocol

        return get_protocol(self.experiment.protocol)

    @model_validator(mode="after")
    def _sync_protocol_registry(self) -> ExperimentConfig:
        """运行时校验：Literal 与协议注册表同步。"""

        if self.experiment.protocol not in protocol_names():
            raise ValueError(f"Unknown protocol: {self.experiment.protocol!r}. Supported: {protocol_names()}")
        return self

    def to_eval_task(self) -> EvalTask:
        """转换为核心模型 EvalTask（供 runner 使用）。"""
        from ..models import EvalTask as CoreEvalTask
        from ..models import SessionSpec as CoreSessionSpec

        data: dict[str, object] = self.task.data.model_dump() if self.task.data else {}
        if self.task.benchmark:
            data["benchmark"] = self.task.benchmark
        if self.task.judgement_mode:
            data["judgement_mode"] = self.task.judgement_mode

        return CoreEvalTask(
            name=self.experiment.name,
            description=self.experiment.description,
            sessions=[
                CoreSessionSpec(
                    id=i + 1,
                    instruction=s.instruction,
                    verifier=s.verifier,
                    memory_inject=s.memory_inject,
                    artifacts=s.artifacts,
                    env_extra=s.env_extra,
                )
                for i, s in enumerate(self.task.sessions)
            ],
            memory_ground_truth=self.task.memory_ground_truth,
            task_ground_truth=self.task.task_ground_truth,
            agent=self.agent.model_dump(),
            data=data,
            benchmark=self.task.benchmark,
            memory_instruction=self.task.memory_instruction,
            task_environment=(self.task.task_environment.model_dump() if self.task.task_environment else {}),
        )
