"""Bounded Harbor 0.22 / Hermes 0.21.3 reproduction entry; no installed files are edited."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shlex
import subprocess
from pathlib import Path

from dumemeval.config import load_config

HERMES_VERSION = "0.21.3"
HERMES_COMMIT = "345cd2b057a452236de401d3534b8502a7465e8d"
HARBOR_VERSION = "0.22.0"
RUNTIME_PROBE = (
    "import importlib.metadata,json,pathlib;"
    f"v=importlib.metadata.version('hermes-agent');assert v=={HERMES_VERSION!r},v;"
    "assert pathlib.Path('/tmp/hermes/skills/persistent-memory/SKILL.md').is_file();"
    f"d={{'runtime':'hermes','version':v,'source_commit':{HERMES_COMMIT!r},"
    "'openai_sdk':importlib.metadata.version('openai'),'harbor_install_hook':'verified_preinstalled'};"
    "p=pathlib.Path('/logs/agent/hermes-runtime.json');p.parent.mkdir(parents=True,exist_ok=True);"
    "p.write_text(json.dumps(d,indent=2),encoding='utf-8');print(json.dumps(d))"
)


def install_local_compatibility() -> None:
    """Apply only the three compatibility changes used by the historical run."""
    import harbor.agents.installed.hermes as hermes_module
    from harbor.agents.installed.hermes import Hermes
    from harbor.environments.base import BaseEnvironment

    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise RuntimeError(f"This reproduction requires Harbor {HARBOR_VERSION}")

    async def use_preinstalled(self: Hermes, environment: BaseEnvironment) -> None:
        await self.exec_as_agent(
            environment,
            command="/opt/hermes/.venv/bin/python -c " + shlex.quote(RUNTIME_PROBE),
            timeout_sec=30,
        )

    # The stock installer is unpinned and finishes with unsupported `hermes version`.
    Hermes.install = use_preinstalled
    Hermes.get_version_command = lambda self: "hermes --version"
    hermes_module._NATIVE_PROVIDERS["openai"] = ("openai-api", ["OPENAI_API_KEY"])


def run_config(config_path: Path, *, check_only: bool = False) -> int:
    """Validate the pinned image, then delegate execution to the normal CLI."""
    from dumemeval.cli import main as cli_main

    cfg = load_config(str(config_path))
    if (cfg.execution.engine, cfg.agent.runtime, cfg.agent.version) != ("harbor", "hermes", HERMES_VERSION):
        raise ValueError("Use the pinned Harbor/Hermes reproduction configuration")
    if not (cfg.agent.model or "").startswith("openai/") or cfg.agent.skills_dir:
        raise ValueError("Use openai/<model> and the skill baked into the image (omit skills_dir)")
    install_local_compatibility()
    image = cfg.execution.environment.docker_image
    if not image:
        raise ValueError("Set execution.environment.docker_image to the pinned Hermes image")
    inspected = json.loads(subprocess.check_output(["docker", "image", "inspect", image], text=True))[0]
    labels = inspected["Config"].get("Labels") or {}
    if labels.get("org.opencontainers.image.revision") != HERMES_COMMIT:
        raise ValueError("Hermes image revision does not match the pinned official source")
    # This check makes no model requests and receives no credentials.
    runtime = json.loads(
        subprocess.check_output(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                image,
                "/opt/hermes/.venv/bin/python",
                "-c",
                RUNTIME_PROBE,
            ],
            text=True,
            timeout=60,
        )
    )
    manifest = {
        "harbor_version": HARBOR_VERSION,
        "docker_image": image,
        "docker_image_id": inspected["Id"],
        "runtime": runtime,
        "launcher_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "compatibility_scope": "Process-local install/version/provider hooks; Hermes.run and export unchanged",
    }
    if check_only:
        print(json.dumps(manifest, indent=2))
        return 0
    output = Path(cfg.output.dir)
    if output.exists() and any(p.name != "preparation.json" for p in output.iterdir()):
        raise ValueError("Preserve previous attempts: choose a fresh MEMORYARENA_CONTROL_RUN")
    env = cfg.execution.environment.env
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        if not env.get(key) or "${" in env[key]:
            raise ValueError(f"Configure {key} through the reproduction environment")
        # Harbor's native provider resolution reads the host environment.
        os.environ[key] = env[key]
    output.mkdir(parents=True, exist_ok=True)
    shared = output.parent / "hermes-inputs.json"
    if shared.exists() and json.loads(shared.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Runtime inputs changed between arms; choose a fresh run label")
    shared.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "hermes-runtime-inputs.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return cli_main(["run", "--config", str(config_path), "--no-resume"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/memoryarena/controlled-math-hermes.yaml")
    )
    parser.add_argument(
        "--check-only", action="store_true", help="Check versions/image/skill without model calls"
    )
    args = parser.parse_args()
    return run_config(args.config, check_only=args.check_only)


if __name__ == "__main__":
    raise SystemExit(main())
