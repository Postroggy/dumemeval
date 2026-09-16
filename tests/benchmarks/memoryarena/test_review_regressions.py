"""Independent PR #5 counterexamples, using deterministic judges and real runner inputs."""

from pathlib import Path
from typing import Any, Literal

import pytest

from dumemeval.adapters.registry import create_adapter
from dumemeval.artifacts.controls import experiment_controls, observed_controls
from dumemeval.benchmarks.memoryarena.metrics.search import MemoryArenaSearchCalculator
from dumemeval.benchmarks.memoryarena.metrics.shopping import MemoryArenaShoppingCalculator
from dumemeval.comparison.service import comparability_warnings
from dumemeval.execution.executor import SessionExecutor
from dumemeval.lifecycle.memory_transfer import MemoryTransfer
from dumemeval.lifecycle.runner import SessionRunner
from dumemeval.metrics.core.base import MetricInput
from dumemeval.models import MemorySpec, RunRef, SampleResult, SessionOutcome, SessionSpec, TaskExecution
from dumemeval.verifier.llm import LLMJudgeVerifier
from tests.benchmarks.memoryarena.test_contracts import shopping_input
from tests.benchmarks.memoryarena.test_search_scoring import search_task
from tests.test_experiment_controls import _config, _run


@pytest.mark.parametrize("first", ["B000000099", None])
def test_wrong_or_missing_first_purchase_does_not_poison_later_round(first: str | None) -> None:
    inp = shopping_input(evidence=True)
    purchases = [] if first is None else [first]
    for index, values in enumerate([purchases, [*purchases, "B000000002"]]):
        evidence = inp.execution.sessions[index].environment
        assert evidence is not None
        evidence.info["purchased_asins"] = [str(asin) for asin in values]
    actual = MemoryArenaShoppingCalculator().calculate(inp)
    assert [d["match_ground_truth"] for d in actual.details] == [False, True]
    assert actual.values == {"match_ground_truth": 0.5, "overall_success": 0.0}


class CaptureInstructions(SessionExecutor):
    def __init__(self) -> None:
        self.instructions: list[str] = []

    async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
        suffix = str(session_ctx.get("instruction_suffix") or "")
        self.instructions.append(session.instruction + ("\n" + suffix if suffix else ""))
        return SessionOutcome(session_id=session.id, success=True, observation="answer")


@pytest.mark.asyncio
async def test_recorded_prompt_covers_runtime_suffix_and_generated_utf8(tmp_path: Path) -> None:
    import hashlib

    from dumemeval.artifacts.provenance import snapshot_run
    from dumemeval.execution.environment import EnvironmentExecutor
    from dumemeval.execution.task_dir import TaskDirGenerator
    from dumemeval.lifecycle.checkpoint import save_task_result
    from dumemeval.task_environments.base import EnvironmentBinding, TaskEnvironmentRuntime

    class Runtime(TaskEnvironmentRuntime):
        def __init__(self, instruction: str) -> None:
            self.instruction = instruction

        def open(self) -> None:
            pass

        def begin_session(self, session: SessionSpec) -> EnvironmentBinding:
            return EnvironmentBinding(instruction=self.instruction)

        def finish_session(self, session: SessionSpec, outcome: SessionOutcome) -> SessionOutcome:
            return outcome

        def close(self) -> None:
            pass

    cfg = _config()
    task = cfg.to_eval_task()
    cfg.protocol_instance.normalize_sessions(task.sessions)

    class Executor(SessionExecutor):
        def __init__(self, directory: Path) -> None:
            self.generator = TaskDirGenerator(tasks_root=directory / "tasks")
            self.instructions: list[bytes] = []

        async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
            path = self.generator.generate(session, instruction_suffix=session_ctx["instruction_suffix"])
            self.instructions.append((path / "instruction.md").read_bytes())
            return SessionOutcome(session_id=session.id, success=True, observation="answer")

    runs = []
    for label, suffix in [("before", "运行时指令甲"), ("after", "运行时指令乙")]:
        directory = tmp_path / label
        executor = Executor(directory)
        execution = await SessionRunner(
            create_adapter(
                MemorySpec.model_validate({**cfg.memory.model_dump(), "path": str(directory / "memory")})
            ),
            EnvironmentExecutor(executor, Runtime(suffix)),
            cfg.protocol_instance,
            memory_transfer=MemoryTransfer(
                transfer_dir=directory / "transfer", mount_source=directory / "mounts"
            ),
            snapshot_dir=directory / "snapshots",
        ).run(task)
        assert all(suffix.encode("utf-8") in value for value in executor.instructions)
        assert [s.instruction_sha256 for s in execution.sessions] == [
            hashlib.sha256(value).hexdigest() for value in executor.instructions
        ]
        save_task_result(directory, execution)
        provenance = snapshot_run(
            cfg, output_dir=directory, config_path="fixture.yaml", mock=False, tasks=[task]
        )
        runs.append(_run(label, provenance.controls))
    assert comparability_warnings(runs) == [
        "Controlled input differs: observed_prompts; this comparison is not a controlled ablation"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["none", "location", "proactive"])
async def test_comparison_agrees_with_actual_protocol_instructions(
    tmp_path: Path, policy: Literal["none", "location", "proactive"]
) -> None:
    on = _config()
    on.task.memory_instruction = policy
    off = on.model_copy(deep=True)
    off.experiment.protocol, off.memory.type = "test_only", "none"
    prompts: list[list[str]] = []
    runs: list[RunRef] = []
    for label, cfg in [("on", on), ("off", off)]:
        task = cfg.to_eval_task()
        cfg.protocol_instance.normalize_sessions(task.sessions)
        spec = cfg.memory.model_copy(update={"path": str(tmp_path / label / "persistent")})
        executor = CaptureInstructions()
        runner = SessionRunner(
            adapter=create_adapter(MemorySpec.model_validate(spec.model_dump())),
            executor=executor,
            protocol=cfg.protocol_instance,
            snapshot_dir=tmp_path / label / "snapshots",
            memory_transfer=MemoryTransfer(
                transfer_dir=tmp_path / label / "transfer", mount_source=tmp_path / label / "mounts"
            ),
        )
        result = await runner.run(task)
        from dumemeval.core.instructions import instruction_digest
        from dumemeval.lifecycle.checkpoint import save_task_result

        assert [outcome.instruction_sha256 for outcome in result.sessions] == [
            instruction_digest(text) for text in executor.instructions
        ]
        save_task_result(tmp_path / label, result)
        prompts.append(executor.instructions)
        controls = experiment_controls(cfg, [task])
        controls["observed_prompts"] = observed_controls(tmp_path / label)["observed_prompts"]
        runs.append(_run(label, controls))
    assert (prompts[0] == prompts[1]) == (policy == "none")
    assert bool(comparability_warnings(runs)) == (prompts[0] != prompts[1])
    assert (
        observed_controls(tmp_path / "on")["observed_prompts"]
        == observed_controls(tmp_path / "off")["observed_prompts"]
    ) == (prompts[0] == prompts[1])


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["B000000099", None])
async def test_shopping_new_episode_keeps_protocol_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: str | None
) -> None:
    import json

    from pydantic import JsonValue

    from dumemeval.benchmarks.memoryarena.environment import runtime as runtime_module
    from dumemeval.benchmarks.memoryarena.environment.client import ArenaClient
    from dumemeval.benchmarks.memoryarena.environment.config import ArenaRuntimeConfig
    from dumemeval.benchmarks.memoryarena.environment.prepare import PreparationReport
    from dumemeval.benchmarks.memoryarena.environment.service import OfficialService
    from dumemeval.execution.environment import EnvironmentExecutor
    from dumemeval.models.environment import EnvironmentEvent, ToolCall

    live: set[str] = set()
    prepared: list[int] = []

    class Client(ArenaClient):
        purchases: list[JsonValue]
        index: int

        def _request(
            self, operation: str, payload: dict[str, JsonValue] | None = None, *, method: str = "POST"
        ) -> dict[str, JsonValue]:
            self.events.append(
                EnvironmentEvent(operation=operation, task_id=self.task_id, status="completed", elapsed_sec=0)
            )
            if operation == "shopping_task":
                assert payload is not None and isinstance(payload["step_index"], int)
                self.index = payload["step_index"]
                prepared.append(self.index)
            if operation == "initialize":
                assert not live, "Previous product environment must close before the next initialization"
                live.add(self.task_id)
            if operation == "reset":
                self.purchases = []
            if operation == "step":
                self.purchases = [first if self.index == 0 else "B000000002"]
            if operation == "close":
                live.remove(self.task_id)
            return {
                "status": "ok",
                "task_id": self.task_id,
                "available_environments": ["webshop"],
                "tools": [{"name": "action"}],
                "observation": {},
                "info": {"purchased_asins": getattr(self, "purchases", [])},
            }

    def start(service: OfficialService) -> None:
        service.url = "http://fixture.invalid"

    monkeypatch.setattr(OfficialService, "start", start)
    monkeypatch.setattr(runtime_module, "ArenaClient", Client)
    monkeypatch.setattr(
        runtime_module,
        "inspect_environment",
        lambda config: PreparationReport(
            ready=True,
            reference=str(config.reference),
            revision=config.revision,
            scene=config.env_name,
        ),
    )
    task = shopping_input(evidence=True).task
    config = ArenaRuntimeConfig(reference=tmp_path / "reference", env_name="webshop")
    runtime = runtime_module.MemoryArenaRuntime(task, config, tmp_path / "run")
    memory = tmp_path / "persistent"

    class Agent(SessionExecutor):
        async def run_session(self, session: SessionSpec, session_ctx: dict[str, Any]) -> SessionOutcome:
            note = memory / "note.txt"
            if session.id == 1:
                note.write_text("Remember the first product.", encoding="utf-8")
            else:
                assert note.read_text(encoding="utf-8") == "Remember the first product."
            assert runtime.gateway is not None
            calls = [ToolCall(request_id="submit", tool="submit", arguments={"answer": "done"})]
            if session.id == 2 or first is not None:
                calls.insert(
                    0, ToolCall(request_id="buy", tool="action", arguments={"action": "click[Buy Now]"})
                )
            for call in calls:
                status, _ = runtime.gateway.dispatch(
                    "Bearer " + session_ctx["agent_env"]["DUMEMEVAL_TOOL_TOKEN"],
                    call.model_dump_json().encode(),
                )
                assert status == 200
            return SessionOutcome(session_id=session.id, success=True)

    cfg = _config()
    cfg.memory.path = str(memory)
    runtime.open()
    try:
        execution = await SessionRunner(
            create_adapter(MemorySpec.model_validate(cfg.memory.model_dump())),
            EnvironmentExecutor(Agent(), runtime),
            cfg.protocol_instance,
            memory_transfer=MemoryTransfer(
                transfer_dir=tmp_path / "transfer", mount_source=tmp_path / "mounts"
            ),
            snapshot_dir=tmp_path / "snapshots",
        ).run(task)
        assert all(s.success for s in execution.sessions)
        assert prepared == [0, 1]
        result = MemoryArenaShoppingCalculator().calculate(MetricInput(task=task, execution=execution))
        assert [d["match_ground_truth"] for d in result.details] == [False, True]
        assert len({s.environment.task_id for s in execution.sessions if s.environment}) == 2
    finally:
        runtime.close()
    assert not live
    trace = json.loads((runtime.directory / "trace.json").read_text(encoding="utf-8"))
    for operation in ["initialize", "reset", "close"]:
        assert sum(event["operation"] == operation for event in trace["lifecycle"]) == 2


def test_missing_skill_content_is_not_silently_comparable(tmp_path: Path) -> None:
    cfg = _config()
    cfg.agent.skills_dir = str(tmp_path / "missing")
    runs = [_run(label, experiment_controls(cfg, [cfg.to_eval_task()])) for label in ["a", "b"]]
    assert any("unverified" in warning for warning in comparability_warnings(runs))


def test_same_path_skill_content_changes_control(tmp_path: Path) -> None:
    cfg = _config()
    skill = tmp_path / "skills" / "search" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    cfg.agent.skills_dir = str(skill.parent.parent)
    skill.write_text("Always search.", encoding="utf-8")
    before = _run("before", experiment_controls(cfg, [cfg.to_eval_task()]))
    skill.write_text("Never search.", encoding="utf-8")
    after = _run("after", experiment_controls(cfg, [cfg.to_eval_task()]))
    assert any("differs: agent_skills;" in warning for warning in comparability_warnings([before, after]))


@pytest.mark.parametrize("answers,expected", [(["yes", "yes", "no"], 1), (["no", "no", "yes"], 0)])
def test_search_preserves_vote_and_all_judge_observations(
    monkeypatch: pytest.MonkeyPatch, answers: list[str], expected: int
) -> None:
    verifier = LLMJudgeVerifier({"prompt": "search_grader", "num_runs": 3})
    raw = [f"correct: {answer}\nconfidence: 90%" for answer in answers]
    responses = iter(raw)
    monkeypatch.setattr(verifier, "_raw_judge", lambda *args: next(responses))
    calculator = MemoryArenaSearchCalculator()
    calculator._llm = verifier
    task = search_task(2)
    result = calculator.calculate(
        MetricInput(
            task=task,
            execution=TaskExecution(
                task_id=task.name,
                task_name=task.name,
                memory_backend="none",
                sessions=[SessionOutcome(session_id=i, success=True, observation="answer") for i in (1, 2)],
            ),
            samples=[
                SampleResult(sample_id=str(i), session_id=i, query=f"q{i - 1}", response="answer")
                for i in (1, 2)
            ],
        )
    )
    assert result.values["accuracy"] == expected
    detail = result.details[0]
    assert detail["judge_score"] == pytest.approx(answers.count("yes") / 3)
    assert detail["judge_runs"] == 3
    assert [item["raw"] for item in detail["judge_observations"]] == raw
    assert [item["score"] for item in detail["judge_observations"]] == [float(a == "yes") for a in answers]


def test_search_keeps_partial_observations_when_judge_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = LLMJudgeVerifier({"prompt": "search_grader", "num_runs": 3, "skip_failed": True})
    answers = iter(["correct: yes", "correct: yes"])
    monkeypatch.setattr(verifier, "_raw_judge", lambda *args: next(answers))
    calculator = MemoryArenaSearchCalculator()
    calculator._llm = verifier
    result = calculator._judge_one("candidate", "reference", "question")
    assert result["score_status"] == "not_measured"
    assert result["judge_runs"] == 2
    assert result["judge_observations"] == [{"raw": "correct: yes", "score": 1.0}] * 2
