"""All official processes share runtime cleanup and stable provenance ownership."""

import json
from pathlib import Path

import pytest

from dumemeval.benchmarks.memoryarena.environment.config import ArenaRuntimeConfig
from dumemeval.benchmarks.memoryarena.environment.runtime import MemoryArenaRuntime
from dumemeval.benchmarks.memoryarena.environment.service import OfficialService
from dumemeval.benchmarks.memoryarena.environment.services import ArenaServices
from dumemeval.models import EvalTask


def test_backend_is_injected_and_versioned_without_ephemeral_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def start(service: OfficialService) -> None:
        service.url = "http://127.0.0.1:12345"
        service.fingerprint.update(
            revision="pinned",
            environment_source_sha256="source",
            python="3.12",
            packages={"fastmcp": "1"},
            port=12345,
        )

    monkeypatch.setattr(OfficialService, "start", start)
    runtime = MemoryArenaRuntime(
        EvalTask(name="shop"), ArenaRuntimeConfig(reference=tmp_path, env_name="webshop"), tmp_path
    )
    runtime.services.start()
    backend = runtime.services.backend
    assert backend is not None
    assert runtime.services.environment_config() == {
        "bootstrap_upstream_env": False,
        "upstream_env_server_base": backend.url,
    }
    runtime._write_artifacts()
    first = json.loads((runtime.directory / "runtime.json").read_text())
    assert first["backends"]["webshop"]["port"] == 12345
    assert first["controls"]["fingerprint"]["backends"]["webshop"]["packages"] == {"fastmcp": "1"}
    backend.url = "http://127.0.0.1:54321"
    backend.fingerprint.update(port=54321, process_exit_code=0, cleanup_status="completed")
    runtime._write_artifacts()
    second = json.loads((runtime.directory / "runtime.json").read_text())
    assert first["controls"] == second["controls"]
    backend.fingerprint["packages"] = {"fastmcp": "2"}
    runtime._write_artifacts()
    third = json.loads((runtime.directory / "runtime.json").read_text())
    assert first["controls"] != third["controls"]
    backend.fingerprint.pop("python")
    runtime._write_artifacts()
    assert json.loads((runtime.directory / "runtime.json").read_text())["controls"]["fingerprint"] == {}


@pytest.mark.parametrize("failure", ["startup", "cleanup", "none"])
def test_runtime_reaps_both_processes_and_records_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    events: list[str] = []

    def start(service: OfficialService) -> None:
        events.append("start:" + service.mode)
        service.fingerprint["cleanup_status"] = "pending"
        if failure == "startup" and service.mode == "webshop":
            raise OSError("partial startup")

    def close(service: OfficialService) -> None:
        events.append("close:" + service.mode)
        service.fingerprint["cleanup_status"] = (
            "failed" if failure == "cleanup" and service.mode == "webshop" else "completed"
        )
        if failure == "cleanup" and service.mode == "webshop":
            raise OSError("cannot reap backend")

    monkeypatch.setattr(OfficialService, "start", start)
    monkeypatch.setattr(OfficialService, "close", close)
    runtime = MemoryArenaRuntime(
        EvalTask(name="shop"), ArenaRuntimeConfig(reference=tmp_path, env_name="webshop"), tmp_path
    )
    if failure == "startup":
        with pytest.raises(OSError, match="partial startup"):
            runtime.services.start()
        # ArenaServices owns rollback for a partial startup; runtime cleanup is idempotent.
        runtime.close()
    else:
        runtime.services.start()
    if failure == "cleanup":
        with pytest.raises(ExceptionGroup):
            runtime.close()
    else:
        if failure == "none":
            runtime.close()
    runtime.close()
    assert events == ["start:environment", "start:webshop", "close:webshop", "close:environment"]
    record = json.loads((runtime.directory / "runtime.json").read_text())
    assert record["cleanup_status"] == ("failed" if failure == "cleanup" else "completed")
    assert record["backends"]["webshop"]["cleanup_status"] == record["cleanup_status"]


def test_reasoning_needs_no_backend(tmp_path: Path) -> None:
    services = ArenaServices(ArenaRuntimeConfig(reference=tmp_path, env_name="math"), tmp_path)
    assert services.backend is None
    assert services.environment_config() == services.provenance() == services.controls() == {}
