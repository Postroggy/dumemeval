"""配置加载：yaml/json → ExperimentConfig（pydantic 强校验）。

设计要点：
- load_config 返回 ExperimentConfig（非裸 dict）——配置加载即校验
- 五段式：experiment/agent/memory/task/execution（+ judging/dataset/output）
- ${ENV_VAR} 模板引用**进程环境变量**（敏感信息不落盘、不扫用户家目录）
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

from ..core.config import ExperimentConfig

_ENV_TEMPLATE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def load_config(path: str | Path) -> ExperimentConfig:
    """加载评测配置（yaml 或 json），pydantic 校验后返回。

    Args:
        path: 配置文件路径（.yaml/.yml/.json）

    Returns:
        ExperimentConfig: 强校验的配置模型

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 格式不支持
        pydantic.ValidationError: 配置不符合模型约束
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        raw = yaml.safe_load(text)
    elif path.suffix == ".json":
        raw = json.loads(text)
    else:
        raise ValueError(f"Unsupported config format: {path.suffix}")

    raw = _resolve_env_templates(raw)
    cfg = ExperimentConfig.model_validate(raw)
    from ..adapters.registry import adapter_names

    if cfg.memory.type not in adapter_names():
        raise ValueError(f"Unknown memory adapter type: {cfg.memory.type!r}. Supported: {adapter_names()}")
    return cfg


def _resolve_env_templates(obj: object) -> object:
    """递归解析 ${ENV_VAR} 模板。

    支持 ${VAR} 和 ${VAR:-default} 两种形式。
    缺失且无默认值 → 报错（避免静默空值）。
    """
    if isinstance(obj, dict):
        return {k: _resolve_env_templates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_templates(v) for v in obj]
    if isinstance(obj, str):
        return _resolve_str(obj)
    return obj


def _resolve_str(value: str) -> str:
    """解析单个字符串里的 env 模板。"""

    def _replace(match: re.Match[str]) -> str:
        var_name, default = match.group(1), match.group(2)
        if var_name in os.environ:
            return os.environ[var_name]
        if default is not None:
            return default
        raise ValueError(f"Environment variable '{var_name}' not found in host environment")

    return _ENV_TEMPLATE.sub(_replace, value)
