"""Backend dependency preflight with isolated missing-SDK fault injection."""

import importlib.util
import sys
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Literal

import pytest

from dumemeval.models.environment import ArenaRuntimeConfig
from dumemeval.task_environments import prepare


@pytest.mark.parametrize("scene", ["math", "phys"])
@pytest.mark.parametrize("worker", [False, True], ids=["host", "configured-worker"])
@pytest.mark.parametrize(
    ("backend", "absent", "expected"),
    [
        (None, "openai", "Worker dependency: openai"),
        ("openai", "openai", "Worker dependency: openai"),
        ("OpenRouter", "openai", "Worker dependency: openai"),
        ("anthropic", "openai", None),
        ("anthropic", "anthropic", "Worker dependency: anthropic"),
        ("google", "google", "Worker dependency: google.genai"),
        ("gemini", "google.genai", "Worker dependency: google.genai"),
        ("gemini", "openai", None),
        ("openai", "google.genai", None),
        ("unsupported", "", "Unsupported Math/Phys backend: unsupported"),
    ],
)
def test_backend_sdk_readiness(
    scene: Literal["math", "phys"],
    worker: bool,
    backend: str | None,
    absent: str,
    expected: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def find_spec(name: str) -> ModuleSpec | None:
        if absent == "google" and name.startswith("google."):
            raise ModuleNotFoundError("No module named 'google'")
        return None if name == absent else ModuleSpec(name, loader=None)

    monkeypatch.setattr(prepare, "verify_reference", lambda *_: {})
    if worker:
        # Real subprocess, with dependency availability controlled only in that interpreter.
        (tmp_path / "sitecustomize.py").write_text(
            "import importlib.util\nfrom importlib.machinery import ModuleSpec\n"
            "def find_spec(name):\n"
            f"    absent = {absent!r}\n"
            "    if absent == 'google' and name.startswith('google.'):\n"
            "        raise ModuleNotFoundError(\"No module named 'google'\")\n"
            "    return None if name == absent else ModuleSpec(name, loader=None)\n"
            "importlib.util.find_spec = find_spec\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    else:
        monkeypatch.setattr(importlib.util, "find_spec", find_spec)
    config = ArenaRuntimeConfig(
        reference=tmp_path,
        env_name=scene,
        python=sys.executable if worker else None,
        env_config={"backend": backend} if backend else {},
    )
    report = prepare.inspect_environment(config)
    assert report.missing == ([expected] if expected else [])
    assert report.ready is (expected is None)
