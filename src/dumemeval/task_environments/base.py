"""Resource and binding contracts shared by environment providers and execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from ..models import SessionOutcome, SessionSpec
from ..models.execution import RuntimeMount


class EnvironmentPreparation(BaseModel):
    """Common preparation status; providers may add their own diagnostic fields."""

    ready: bool = False
    missing: list[str] = Field(default_factory=list)


class EnvironmentBinding(BaseModel):
    """Only agent-visible resources; grading references never belong here."""

    env: dict[str, str] = Field(default_factory=dict)
    mounts: list[RuntimeMount] = Field(default_factory=list)
    instruction: str = ""


class TaskEnvironmentRuntime(ABC):
    """Own one task environment independently of conversation and memory state."""

    @abstractmethod
    def open(self) -> None:
        """Prepare owned services and the scenario's initial environment state."""

    @abstractmethod
    def begin_session(self, session: SessionSpec) -> EnvironmentBinding:
        """Apply the scenario's episode boundary and issue a fresh capability."""

    def set_session_context(self, session_ctx: dict[str, Any]) -> None:
        """Receive generic protocol state before binding a session, when needed."""
        return None

    @abstractmethod
    def finish_session(self, session: SessionSpec, outcome: SessionOutcome) -> SessionOutcome:
        """Revoke the capability and attach host-captured execution evidence."""

    @abstractmethod
    def close(self) -> None:
        """Revoke access and release all owned resources, including after failure."""
