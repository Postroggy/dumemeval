"""Memory 后端注册表（懒加载：缺失依赖的后端不影响其他后端）。

与其它扩展点（protocol / benchmark / calculator / task_environment）同一套范式：
``register_adapter`` 是类装饰器，注册键取 ``cls.type_name``（对应
``MemorySpec.type``）。懒加载保留：registry 只存类，不 import 任何 adapter
模块；``create_adapter`` 找不到时按需 ``__import__`` 对应模块并重新查询。
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import MemorySpec
    from .base import BaseMemoryAdapter

# 懒加载注册表：type_name -> adapter 类（首次 create_adapter 时按需 import 模块）
_ADAPTER_REGISTRY: dict[str, type[BaseMemoryAdapter]] = {}


def register_adapter(cls: type[BaseMemoryAdapter]) -> type[BaseMemoryAdapter]:
    """注册 adapter（类装饰器，与其它 register_* 同范式）。

    用法：
        @register_adapter
        class DirectoryMemoryAdapter(BaseMemoryAdapter):
            type_name = "directory"
            ...
    """
    key = cls.type_name or cls.__name__
    _ADAPTER_REGISTRY[key] = cls
    return cls


def create_adapter(spec: MemorySpec) -> BaseMemoryAdapter:
    """根据 MemorySpec.type 创建对应 adapter。

    注册表里没有时先确保内置模块已加载（缺失依赖的后端不影响其它后端；
    加载后仍找不到才报错）。
    """
    cls = _ADAPTER_REGISTRY.get(spec.type)
    if cls is None:
        _ensure_builtin_modules()
        cls = _ADAPTER_REGISTRY.get(spec.type)
    if cls is None:
        raise ValueError(f"Unknown memory adapter type: {spec.type!r}. Supported: {adapter_names()}")
    return cls(spec)


def _ensure_builtin_modules() -> None:
    """逐个 import 内置 adapter 模块，触发 @register_adapter。

    缺失依赖的模块单独 try/except——一个后端装不上不影响其它后端。
    """
    for type_name in ("directory", "http", "hermes_builtin", "everos", "none"):
        if type_name in _ADAPTER_REGISTRY:
            continue
        with contextlib.suppress(ImportError):
            __import__(f"{__package__}.{type_name}", fromlist=["*"])  # 依赖缺失：留作未注册


def adapter_names() -> list[str]:
    """已注册的 adapter 类型名。"""
    _ensure_builtin_modules()
    return list(_ADAPTER_REGISTRY)
