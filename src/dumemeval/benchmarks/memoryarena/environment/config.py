"""Pinned MemoryArena server and runtime configuration.

Source: https://github.com/ZexueHe/MemoryArena
"""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, JsonValue, field_validator

from dumemeval.models.memoryarena import arena_scene


class SceneConfig(BaseModel):
    env_name: str

    @field_validator("env_name")
    @classmethod
    def validate_scene(cls, value: str) -> str:
        arena_scene(value)
        return value


class ArenaConnection(SceneConfig):
    """Connection to a provisioned, pinned MemoryArena environment server."""

    base_url: str
    timeout_sec: float = Field(default=30, gt=0)
    env_config: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("Environment URL must use http or https and include a host")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Environment URL must not contain credentials, query, or fragment")
        return value.rstrip("/")


class ArenaRuntimeConfig(SceneConfig):
    """Pinned official implementation and explicitly provisioned runtime inputs."""

    reference: Path
    revision: str = "6cd9de14b71915e39ac742a20dc33785e14b6aab"
    python: str | None = None
    seed: int = 0
    timeout_sec: float = Field(default=120, gt=0)
    startup_timeout_sec: float = Field(default=90, gt=0)
    max_actions: int = Field(default=64, ge=1, le=1000)
    gateway_host: str = "0.0.0.0"
    agent_host: str = "host.docker.internal"
    env_config: dict[str, JsonValue] = Field(default_factory=dict)
    tools_config: dict[str, JsonValue] = Field(default_factory=dict)
    service_env: dict[str, str] = Field(default_factory=dict)
