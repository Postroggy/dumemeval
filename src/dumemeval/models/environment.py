"""Host-captured environment evidence shared across dataset integrations."""

from typing import Literal

from pydantic import BaseModel, Field, JsonValue


class EnvironmentControls(BaseModel):
    """Provider-selected stable inputs, separate from transient runtime metadata."""

    task_id: str = Field(min_length=1)
    fingerprint: dict[str, JsonValue] = Field(default_factory=dict)
    uncontrolled: list[str] = Field(default_factory=list)


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
