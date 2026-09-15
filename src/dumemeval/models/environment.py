"""Typed official environment evidence, separate from agent claims and rewards."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, JsonValue, field_validator


class ArenaConnection(BaseModel):
    """Connection to a provisioned, pinned MemoryArena environment server."""

    base_url: str
    env_name: Literal["webshop", "travel_planner", "browsecomp-plus", "math", "phys"]
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


class EnvironmentEvidence(BaseModel):
    """Host-captured evidence; source distinguishes official responses from submissions."""

    task_id: str
    env_name: str
    operation: str
    observation: dict[str, JsonValue] = Field(default_factory=dict)
    info: dict[str, JsonValue] = Field(default_factory=dict)
    reward: float | bool | None = None
    done: bool | None = None
    session_id: int | None = Field(default=None, ge=1)
    action_id: str | None = None
    sequence: int = Field(default=0, ge=0)
    tool: str | None = None
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    result: JsonValue = None
    status: Literal["completed", "failed", "ambiguous"] = "completed"
    source: Literal["official_environment", "official_tool", "agent_submission"] = "official_environment"
    elapsed_sec: float = Field(default=0, ge=0)


class EnvironmentEvent(BaseModel):
    """A payload-free transport trace; sensitive configuration is never logged."""

    operation: str
    task_id: str
    status: Literal["completed", "failed", "ambiguous"]
    elapsed_sec: float = Field(ge=0)
    error_type: str | None = None


class ToolCall(BaseModel):
    """A delivery identity is scoped to one session and one immutable request."""

    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ArenaRuntimeConfig(BaseModel):
    """Pinned official implementation and explicitly provisioned runtime inputs."""

    reference: Path
    revision: str = "6cd9de14b71915e39ac742a20dc33785e14b6aab"
    env_name: Literal["webshop", "travel_planner", "browsecomp-plus", "math", "phys"]
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
