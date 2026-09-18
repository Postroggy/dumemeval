"""Scenario semantics behind the shared task runtime, using official implementations."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import cast

from pydantic import BaseModel, JsonValue, TypeAdapter

from dumemeval.models import EvalTask, SessionSpec
from dumemeval.models.environment import EnvironmentEvidence, ToolCall
from dumemeval.models.memoryarena import SceneFamily, arena_scene

from .client import ArenaClient
from .config import ArenaRuntimeConfig

_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class ToolResult(BaseModel):
    result: JsonValue = None
    evidence: EnvironmentEvidence | None = None


class ArenaScenario(ABC):
    seed_policy = "deterministic_initial_state"
    reset_per_session = False

    def __init__(self, task: EvalTask, config: ArenaRuntimeConfig, directory: Path) -> None:
        self.task, self.config, self.directory = task, config, directory

    def reset_seed(self) -> int:
        return self.config.seed

    def prepare_session(self, client: ArenaClient, session: SessionSpec) -> None:
        """Prepare a scene-defined episode without changing the memory lifecycle."""
        return None

    def session_instruction(self, session: SessionSpec, *, memory_enabled: bool) -> str:
        """Provide scenario context for the current isolated conversation."""
        return ""

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

    def finalize_submission(self, evidence: EnvironmentEvidence, records: list[EnvironmentEvidence]) -> None:
        """Attach scenario scoring evidence captured by the host in this session."""
        return None

    def feedback(self, evidence: EnvironmentEvidence) -> dict[str, JsonValue]:
        return {"submitted": True}

    def memory_entry(self, evidence: EnvironmentEvidence) -> str | None:
        """Return host-captured history for the configured memory adapter."""
        return None


class ReasoningScenario(ArenaScenario):
    def submit(self, client: ArenaClient, session: SessionSpec, answer: str) -> EnvironmentEvidence:
        return client.step(
            {"type": "final", "answer": answer}, ground_truth=self.reference_answer(session), need_judge=True
        )


class TravelScenario(ArenaScenario):
    seed_policy = "official_group_id"

    def __init__(self, task: EvalTask, config: ArenaRuntimeConfig, directory: Path) -> None:
        super().__init__(task, config, directory)
        self.previous_plans: list[str] = []
        self.previous_feedback: list[str] = []
        self.history_mode = ""
        self.history_rounds = 0

    def session_instruction(self, session: SessionSpec, *, memory_enabled: bool) -> str:
        if self.task.data.get("execution_flow") != "official_travel":
            return ""
        self.history_mode = "memory_on" if memory_enabled else "memory_off"
        self.history_rounds = len(self.previous_plans)
        base = self.task.data.get("base_person")
        base = base if isinstance(base, dict) else {}
        if memory_enabled:
            return (
                "Retrieve the base traveler's confirmed plan from persistent memory when present. "
                "Store each submitted plan and its feedback for later travelers."
            )
        name = str(base.get("name", ""))
        base_plan = _format_travel_plan(name, base.get("daily_plans", [])) if base else ""
        context = ""
        if base:
            context = (
                f"=== {name}'s Request (Already Planned) ===\n"
                f"{name} has already made their travel request and their plan has been finalized.\n"
                f"{name}'s Query: {base.get('query', '')}\n"
                f"=== {name}'s Confirmed Plan ===\n{base_plan}\n"
                f"Generate plans for all travelers except {name}.\n"
            )
        if self.previous_plans:
            questions = self.task.data.get("questions", [])
            prior_queries = [
                f"{item.get('name', '')}: {item.get('query', '')}"
                for item in questions[: len(self.previous_plans)]
                if isinstance(item, dict)
            ]
            context += (
                "\n=== All Travelers' Queries ===\n"
                + (f"{name}: {base.get('query', '')}\n" if base else "")
                + "\n".join(prior_queries)
                + "\n=== Previous Plan ===\n"
                + "\n\n".join(([base_plan] if base_plan else []) + self.previous_plans)
                + "\n=== Judgement ===\n"
                + "\n\n".join(self.previous_feedback)
                + "\n=== New Traveler ===\n"
            )
        return context

    def feedback(self, evidence: EnvironmentEvidence) -> dict[str, JsonValue]:
        return {"submitted": True, "judgement": evidence.info.get("judgement", "")}

    def memory_entry(self, evidence: EnvironmentEvidence) -> str | None:
        if self.task.data.get("execution_flow") != "official_travel" or self.history_mode != "memory_on":
            return None
        answer = evidence.arguments.get("answer")
        round_index = evidence.info.get("history_rounds")
        if not isinstance(answer, str) or not isinstance(round_index, int):
            return None
        questions = self.task.data.get("questions")
        if not isinstance(questions, list) or not 0 <= round_index < len(questions):
            return None
        question = questions[round_index]
        if not isinstance(question, dict):
            return None
        return json.dumps(
            {
                "name": question.get("name", ""),
                "query": question.get("query", ""),
                "scratchpad": "",
                "final_plan": answer,
                **(
                    {"judgement": evidence.info["judgement"]}
                    if isinstance(evidence.info.get("judgement"), str)
                    else {}
                ),
            },
            ensure_ascii=False,
        )

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
        evidence = client.step(answer, ground_truth=reference, need_judge=True)
        if self.task.data.get("execution_flow") == "official_travel":
            evidence.info["history_mode"] = self.history_mode
            evidence.info["history_rounds"] = self.history_rounds
            self.previous_plans.append(answer)
            feedback = evidence.info.get("judgement")
            if isinstance(feedback, str) and feedback:
                self.previous_feedback.append(feedback)
        return evidence


def _format_travel_plan(name: str, days: JsonValue) -> str:
    lines = [f"=== {name}'s Plan ==="]
    if isinstance(days, list):
        for day in days:
            if not isinstance(day, dict):
                continue
            lines.append(f"Day {day.get('days') or day.get('day')}:")
            for slot in (
                "current_city",
                "transportation",
                "breakfast",
                "attraction",
                "lunch",
                "dinner",
                "accommodation",
            ):
                lines.append(f"{slot.replace('_', ' ').title()}: {day.get(slot, '-')}")
            lines.append("")
    return "\n".join(lines)


class SearchScenario(ArenaScenario):
    def finalize_submission(self, evidence: EnvironmentEvidence, records: list[EnvironmentEvidence]) -> None:
        evidence.info["retrieval_actions"] = [
            record.action_id
            for record in records
            if record.task_id == evidence.task_id
            and record.session_id == evidence.session_id
            and record.status == "completed"
            and record.source == "official_tool"
            and record.tool in {"search", "get_document"}
            and record.action_id
        ]

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
        purchases = evidence.observation.get("purchases")
        if isinstance(purchases, list):
            products: list[JsonValue] = []
            for purchase in purchases:
                if not isinstance(purchase, dict) or not isinstance(purchase.get("asin"), str):
                    continue
                asin = str(purchase["asin"]).upper()
                try:
                    name = client.shopping_product(asin)
                except (RuntimeError, ValueError) as exc:
                    evidence.info["attribute_lookup_error"] = type(exc).__name__
                    name = None
                products.append({"asin": asin, "name": name, "price": purchase.get("price")})
            evidence.info["purchased_products"] = products
        return evidence


SCENARIOS: dict[SceneFamily, type[ArenaScenario]] = {
    "shopping": ShoppingScenario,
    "travel": TravelScenario,
    "search": SearchScenario,
    "reasoning": ReasoningScenario,
}


def scenario_type(name: str) -> type[ArenaScenario]:
    return SCENARIOS[arena_scene(name).family]
