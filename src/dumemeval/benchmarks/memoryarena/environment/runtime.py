"""One registered MemoryArena runtime per independent evaluation task."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from pydantic import JsonValue

from dumemeval.models import EvalTask, SessionOutcome, SessionSpec
from dumemeval.models.environment import EnvironmentControls, EnvironmentEvidence, ToolCall
from dumemeval.models.execution import RuntimeMount
from dumemeval.task_environments import agent_tool
from dumemeval.task_environments.base import EnvironmentBinding, TaskEnvironmentRuntime
from dumemeval.task_environments.gateway import ToolGateway

from .client import ArenaClient
from .config import ArenaConnection, ArenaRuntimeConfig
from .prepare import inspect_environment
from .scenarios import SCENARIOS
from .service import OfficialService


class MemoryArenaRuntime(TaskEnvironmentRuntime):
    """Tools see only a session capability; official control and evidence stay here."""

    def __init__(self, task: EvalTask, config: ArenaRuntimeConfig, output_dir: Path) -> None:
        self.task = task
        self.config = config
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", task.name)[:80]
        self.directory = (
            output_dir / "environments" / f"{safe_name}-{hashlib.sha256(task.name.encode()).hexdigest()[:8]}"
        )
        self.service = OfficialService(config, self.directory)
        self.scenario = SCENARIOS[config.env_name](task, config, self.directory)
        self.client: ArenaClient | None = None
        self._clients: list[ArenaClient] = []
        self.gateway: ToolGateway | None = None
        self.session: SessionSpec | None = None
        self.evidence: list[EnvironmentEvidence] = []
        self.catalog: list[JsonValue] = []
        self._submitted = False
        self._closed = False
        self._cleanup_status = "pending"
        self._reset_seed = config.seed

    def open(self) -> None:
        preparation = inspect_environment(self.config)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "preparation.json").write_text(
            preparation.model_dump_json(indent=2), encoding="utf-8"
        )
        self.service.fingerprint["assets"] = dict(preparation.assets)
        if not preparation.ready:
            raise RuntimeError("Environment preparation incomplete: " + "; ".join(preparation.missing))
        self.service.start()
        env_config = dict(self.config.env_config)
        self.client = ArenaClient(
            ArenaConnection(
                base_url=self.service.url,
                env_name=self.config.env_name,
                env_config=env_config,
                timeout_sec=self.config.timeout_sec,
            )
        )
        self._clients.append(self.client)
        deadline = time.monotonic() + self.config.startup_timeout_sec
        while True:
            try:
                self.client.available()
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        self.scenario.prepare(self.client)
        if not self.scenario.reset_per_session:
            self._initialize_episode()
        self.gateway = ToolGateway(self.config.gateway_host, self._call, self.config.max_actions)
        self.gateway.start()
        self._write_artifacts()

    def _initialize_episode(self, session_id: int | None = None) -> None:
        assert self.client is not None
        self.client.initialize()
        seed = self.scenario.reset_seed()
        reset = self.client.reset(seed=seed)
        reset.session_id = session_id
        reset.sequence = len(self.evidence)
        self.evidence.append(reset)
        self._reset_seed = seed
        self.scenario.validate_reset(self.evidence[-1])
        self.catalog = self.client.tools()

    def begin_session(self, session: SessionSpec) -> EnvironmentBinding:
        if self.gateway is None or self.client is None or self._closed:
            raise RuntimeError("Task environment is not open")
        if self.scenario.reset_per_session:
            self.client.close()
            self.client = ArenaClient(
                ArenaConnection(
                    base_url=self.service.url,
                    env_name=self.config.env_name,
                    env_config=dict(self.config.env_config),
                    timeout_sec=self.config.timeout_sec,
                )
            )
            self._clients.append(self.client)
            self.scenario.prepare_session(self.client, session)
            self._initialize_episode(session.id)
        self.session = session
        self._submitted = False
        token = self.gateway.bind()
        self.service.redactor.secrets.append(token)
        self.service.redactor.secrets.sort(key=len, reverse=True)
        command = "python /opt/dumemeval/arena_tool.py"
        return EnvironmentBinding(
            env={
                "DUMEMEVAL_TOOL_URL": f"http://{self.config.agent_host}:{self.gateway.port}/tool",
                "DUMEMEVAL_TOOL_TOKEN": token,
                "DUMEMEVAL_TOOL_TIMEOUT": str(self.config.timeout_sec + 5),
            },
            mounts=[
                RuntimeMount(
                    host_path=str(Path(agent_tool.__file__).resolve()),
                    container_path="/opt/dumemeval/arena_tool.py",
                )
            ],
            instruction=(
                f"Official scenario tools are available through `{command} TOOL 'JSON_ARGUMENTS'`.\n"
                f"Run `{command} tools` to inspect them. Each call returns an actual tool observation.\n"
                "If delivery is uncertain, retry the identical command; its pending request ID is retained. "
                "Do not change tools/arguments while a request is pending. For an explicitly identified "
                "logical action, use --request-id ID and reuse that ID on retries.\n"
                "Use the container's Python/Bash tools for coding; all code runs in this isolated session.\n"
                f'For every question, finish with `{command} submit \'{{"answer":"your final answer"}}\'`.\n'
                "For shopping, perform actual action calls through Buy Now before submitting.\n"
                "Do not reset the environment or guess previous observations. "
                "This session has a fresh conversation; only configured memory transfers between sessions.\n"
                "A session without a question only ingests the provided context and does not submit an answer."
            ),
        )

    def _call(self, call: ToolCall) -> JsonValue:
        if self.session is None or self.client is None:
            raise RuntimeError("No active session")
        if call.tool == "tools":
            return [
                *self.catalog,
                {"name": "submit", "description": "Finish this round; arguments: {answer: string}."},
            ]
        if self._submitted:
            raise ValueError("This round is already submitted")
        start = time.monotonic()
        evidence = EnvironmentEvidence(
            task_id=self.client.task_id,
            env_name=self.config.env_name,
            operation="tool",
            session_id=self.session.id,
            action_id=call.request_id,
            sequence=len(self.evidence),
            tool=call.tool,
            arguments=call.arguments,
            source="official_tool",
        )
        try:
            if call.tool == "submit":
                if self.session.query is None:
                    raise ValueError("Context-only sessions cannot submit")
                answer = call.arguments.get("answer")
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("submit requires a non-empty answer")
                evidence = self._submit(answer, evidence)
                self._submitted = True
                result: JsonValue = self.scenario.feedback(evidence)
            else:
                reply = self.scenario.invoke(self.client, call)
                result = reply.result
                if reply.evidence:
                    evidence = reply.evidence.model_copy(
                        update={
                            k: getattr(evidence, k)
                            for k in ("session_id", "action_id", "sequence", "tool", "arguments")
                        }
                    )
            evidence.result = result
            return result
        except (RuntimeError, ValueError, KeyError):
            evidence.status = (
                "ambiguous"
                if self.client.events and self.client.events[-1].status == "ambiguous"
                else "failed"
            )
            raise
        finally:
            evidence.elapsed_sec = time.monotonic() - start
            self.evidence.append(evidence)
            self._write_artifacts()

    def _submit(self, answer: str, evidence: EnvironmentEvidence) -> EnvironmentEvidence:
        assert self.client and self.session
        reply = self.scenario.submit(self.client, self.session, answer)
        return reply.model_copy(
            update={
                "session_id": evidence.session_id,
                "action_id": evidence.action_id,
                "sequence": evidence.sequence,
                "tool": evidence.tool,
                "arguments": evidence.arguments,
            }
        )

    def finish_session(self, session: SessionSpec, outcome: SessionOutcome) -> SessionOutcome:
        if self.gateway:
            self.gateway.revoke()
        records = [e for e in self.evidence if e.session_id == session.id]
        submitted = next(
            (e for e in reversed(records) if e.tool == "submit" and e.status == "completed"), None
        )
        if submitted:
            outcome.environment = submitted
            outcome.observation = str(submitted.arguments["answer"])
        if session.query is not None and submitted is None:
            outcome.success = False
            outcome.error = outcome.error or "Agent did not submit a result through the environment tools"
        if any(e.status != "completed" for e in records):
            outcome.success = False
            outcome.error = outcome.error or "Environment tool execution failed; see environment trace"
        outcome.artifacts["environment_trace"] = self.directory / "trace.json"
        outcome.artifacts["environment_provenance"] = self.directory / "runtime.json"
        self.session = None
        self._write_artifacts()
        return SessionOutcome.model_validate_json(self.service.redactor.text(outcome.model_dump_json()))

    def _write_artifacts(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        trace = {
            "task_id": self.task.name,
            "environment_id": self.client.task_id if self.client else None,
            "evidence": [e.model_dump() for e in self.evidence],
            "lifecycle": [e.model_dump() for client in self._clients for e in client.events],
            "closed": self._closed,
        }
        runtime = {
            **self.service.fingerprint,
            "seed": self._reset_seed,
            "seed_policy": self.scenario.seed_policy,
            "env_name": self.config.env_name,
            "environment_state": "per_session" if self.scenario.reset_per_session else "per_task",
            "conversation_state": "per_session",
            "closed": self._closed,
            "cleanup_status": self._cleanup_status,
            "config": self.config.model_dump(mode="json"),
        }
        stable_keys = (
            "revision",
            "environment_source_sha256",
            "env_name",
            "environment_state",
            "seed",
            "seed_policy",
            "python",
            "fastapi",
            "uvicorn",
            "assets",
            "packages",
        )
        runtime["controls"] = EnvironmentControls(
            task_id=self.task.name,
            fingerprint=(
                {key: runtime.get(key) for key in stable_keys}
                if all(runtime.get(key) for key in ("revision", "environment_source_sha256", "python"))
                else {}
            ),
            uncontrolled=(
                ["environment_seed"] if self.scenario.seed_policy == "upstream_wall_clock_seed" else []
            ),
        ).model_dump(mode="json")
        for name, payload in (("trace.json", trace), ("runtime.json", runtime)):
            (self.directory / name).write_text(
                self.service.redactor.text(json.dumps(payload, indent=2, ensure_ascii=False)),
                encoding="utf-8",
            )

    def close(self) -> None:
        if self._closed:
            return
        errors: list[Exception] = []
        resources = [self.gateway, self.client, self.scenario, self.service]
        for resource in resources:
            if resource is not None:
                try:
                    resource.close()
                except Exception as exc:
                    errors.append(exc)
        self._closed = True
        self._cleanup_status = "failed" if errors else "completed"
        self._write_artifacts()
        if errors:
            raise ExceptionGroup("Environment resource cleanup failed", errors)
