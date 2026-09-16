"""Scenario semantics behind the shared task runtime, using official implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import cast

from pydantic import BaseModel, JsonValue, TypeAdapter

from dumemeval.models import EvalTask, SessionSpec
from dumemeval.models.environment import EnvironmentEvidence, ToolCall

from .client import ArenaClient
from .config import ArenaRuntimeConfig
from .service import OfficialService

_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class ToolResult(BaseModel):
    result: JsonValue = None
    evidence: EnvironmentEvidence | None = None


class ArenaScenario(ABC):
    seed_policy = "deterministic_initial_state"
    reset_per_session = False

    def __init__(self, task: EvalTask, config: ArenaRuntimeConfig, directory: Path) -> None:
        self.task, self.config, self.directory = task, config, directory

    def prepare(self, client: ArenaClient) -> None:
        """Prepare scenario resources before initializing the official environment."""
        return None

    def reset_seed(self) -> int:
        return self.config.seed

    def prepare_session(self, client: ArenaClient, session: SessionSpec) -> None:
        """Prepare a scene-defined episode without changing the memory lifecycle."""
        return None

    def validate_reset(self, evidence: EnvironmentEvidence) -> None:
        """Validate any environment-selected task data against the pinned input."""
        return None

    def invoke(self, client: ArenaClient, call: ToolCall) -> ToolResult:
        return ToolResult(result=client.tool(call.tool, call.arguments))

    def reference_answer(self, session: SessionSpec) -> JsonValue:
        scored = [s for s in self.task.sessions if s.query is not None]
        index = next(i for i, s in enumerate(scored) if s.id == session.id)
        return _JSON.validate_python(self.task.data["answers"][index])

    @abstractmethod
    def submit(self, client: ArenaClient, session: SessionSpec, answer: str) -> EnvironmentEvidence:
        """Submit with the host's reference; agents cannot choose their grading inputs."""

    def close(self) -> None:
        """Release scenario-specific resources after the environment has closed."""
        return None

    def feedback(self, evidence: EnvironmentEvidence) -> dict[str, JsonValue]:
        return {"submitted": True}


class ReasoningScenario(ArenaScenario):
    def submit(self, client: ArenaClient, session: SessionSpec, answer: str) -> EnvironmentEvidence:
        return client.step(
            {"type": "final", "answer": answer}, ground_truth=self.reference_answer(session), need_judge=True
        )


class TravelScenario(ArenaScenario):
    seed_policy = "official_group_id"

    def feedback(self, evidence: EnvironmentEvidence) -> dict[str, JsonValue]:
        return {"submitted": True, "judgement": evidence.info.get("judgement", "")}

    def reset_seed(self) -> int:
        return int(self.task.data["sample_id"])

    def validate_reset(self, evidence: EnvironmentEvidence) -> None:
        observation = evidence.observation
        if observation.get("base_person") != self.task.data.get("base_person"):
            raise ValueError("Official Travel environment data differs from the pinned task")
        source_questions = observation.get("questions")
        source_answers = observation.get("answers")
        if not isinstance(source_questions, list) or not isinstance(source_answers, list):
            raise ValueError("Official Travel reset lacks task data")
        for index, question in enumerate(self.task.data["questions"]):
            if (
                index >= len(source_questions)
                or index >= len(source_answers)
                or source_questions[index] != question
            ):
                raise ValueError("Official Travel question identity changed")
            expected = self.task.data["answers"][index]
            expected_plans = expected.get("daily_plans", expected) if isinstance(expected, dict) else expected
            actual = source_answers[index]
            if not isinstance(actual, dict) or actual.get("daily_plans") != expected_plans:
                raise ValueError("Official Travel reference answers changed")

    def submit(self, client: ArenaClient, session: SessionSpec, answer: str) -> EnvironmentEvidence:
        gold = self.reference_answer(session)
        rounds = [s for s in self.task.sessions if s.query is not None]
        index = next(i for i, s in enumerate(rounds) if s.id == session.id)
        reference: dict[str, JsonValue] = dict(gold) if isinstance(gold, dict) else {"daily_plans": gold}
        reference.update(
            name=str(self.task.data["questions"][index]["name"]),
            judgement_mode=str(self.task.data.get("judgement_mode", "none")),
        )
        return client.step(answer, ground_truth=reference, need_judge=True)


class SearchScenario(ArenaScenario):
    def submit(self, client: ArenaClient, session: SessionSpec, answer: str) -> EnvironmentEvidence:
        # Upstream step runs its own agent. Its registered search tools are used
        # directly; external-agent answers go to the official grader in evaluation.
        return EnvironmentEvidence(
            task_id=client.task_id,
            env_name=self.config.env_name,
            operation="submit",
            observation={"final": answer},
            source="agent_submission",
        )


class ShoppingScenario(ArenaScenario):
    seed_policy = "upstream_wall_clock_seed"
    reset_per_session = True

    def __init__(self, task: EvalTask, config: ArenaRuntimeConfig, directory: Path) -> None:
        super().__init__(task, config, directory)
        self.upstream = OfficialService(config, directory / "webshop", mode="webshop")

    def prepare(self, client: ArenaClient) -> None:
        self.upstream.start()

    def prepare_session(self, client: ArenaClient, session: SessionSpec) -> None:
        rounds = [item for item in self.task.sessions if item.query is not None]
        index = next(i for i, item in enumerate(rounds) if item.id == session.id)
        path = self.directory.resolve() / f"official-task-{session.id}.json"
        row = cast(
            dict[str, JsonValue],
            _JSON.validate_python(
                {
                    "id": self.task.data.get("sample_id"),
                    "category": self.task.data.get("category", ""),
                    "questions": self.task.data["questions"],
                    "answers": self.task.data["answers"],
                }
            ),
        )
        client.shopping_task(row, str(path), step_index=index)
        client.config.env_config.update(
            task_file=str(path),
            reuse_env=False,
            bootstrap_upstream_env=False,
            upstream_env_server_base=self.upstream.url,
        )

    def invoke(self, client: ArenaClient, call: ToolCall) -> ToolResult:
        action = call.arguments.get("action")
        if (
            call.tool != "action"
            or not isinstance(action, str)
            or not action.startswith(("search[", "click["))
            or not action.endswith("]")
        ):
            raise ValueError("Invalid WebShop action")
        evidence = client.step(action)
        public = {
            k: v for k, v in evidence.observation.items() if k in {"state", "turn_idx", "purchases", "done"}
        }
        return ToolResult(result=public, evidence=evidence)

    def submit(self, client: ArenaClient, session: SessionSpec, answer: str) -> EnvironmentEvidence:
        evidence = client.observation()
        evidence.info["episode_scope"] = "session"
        return evidence

    def close(self) -> None:
        self.upstream.close()


SCENARIOS: dict[str, type[ArenaScenario]] = {
    "webshop": ShoppingScenario,
    "travel_planner": TravelScenario,
    "browsecomp-plus": SearchScenario,
    "math": ReasoningScenario,
    "phys": ReasoningScenario,
}
