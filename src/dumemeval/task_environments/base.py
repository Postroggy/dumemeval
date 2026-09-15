"""Resource and binding contracts shared by environment providers and execution."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from ..models import SessionOutcome, SessionSpec
from ..models.execution import RuntimeMount


class EnvironmentBinding(BaseModel):
    """Only agent-visible resources; grading references never belong here."""

    env: dict[str, str] = Field(default_factory=dict)
    mounts: list[RuntimeMount] = Field(default_factory=list)
    instruction: str = ""


class TaskEnvironmentRuntime(ABC):
    """Own one task environment independently of conversation and memory state."""

    @abstractmethod
    def open(self) -> None:
        """Prepare services, verify readiness, initialize and reset once."""

    @abstractmethod
    def begin_session(self, session: SessionSpec) -> EnvironmentBinding:
        """Issue a fresh session capability without resetting the environment."""

    @abstractmethod
    def finish_session(self, session: SessionSpec, outcome: SessionOutcome) -> SessionOutcome:
        """Revoke the capability and attach host-captured execution evidence."""

    @abstractmethod
    def close(self) -> None:
        """Revoke access and release all owned resources, including after failure."""
