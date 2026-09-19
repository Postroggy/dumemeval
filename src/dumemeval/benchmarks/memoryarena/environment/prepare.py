"""Reproducible source preparation and explicit missing-asset diagnostics."""

from __future__ import annotations

import glob
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

from pydantic import Field

from dumemeval.models.memoryarena import arena_scene
from dumemeval.task_environments.base import EnvironmentPreparation

from .config import ArenaRuntimeConfig
from .service import verify_reference


class PreparationReport(EnvironmentPreparation):
    reference: str
    revision: str
    scene: str
    sources: dict[str, str] = Field(default_factory=dict)
    assets: dict[str, str] = Field(default_factory=dict)


def checksum(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _uses_tokenizer(config: ArenaRuntimeConfig) -> bool:
    tokens = config.tools_config.get("snippet_max_tokens", 512)
    if tokens is None:
        return False
    if not isinstance(tokens, int) or isinstance(tokens, bool):
        raise ValueError("Search snippet_max_tokens must be an integer or null")
    return tokens > 0


def required_assets(config: ArenaRuntimeConfig) -> list[str]:
    family = arena_scene(config.env_name).family
    if family == "travel":
        root = Path(
            str(
                config.tools_config.get("database")
                or config.reference / "env/env_systems/travel_planner_env/database"
            )
        )
        return [
            str(root / path)
            for path in (
                "flights/clean_Flights_2022.csv",
                "restaurants/clean_restaurant_2022.csv",
                "accommodations/clean_accommodations_2022.csv",
                "attractions/attractions.csv",
                "googleDistanceMatrix/distance.csv",
                "background/citySet_with_states.txt",
            )
        ]
    if family == "shopping":
        root = Path(
            config.service_env.get("MEMORYARENA_WEBSHOP_DATA_ROOT", str(config.reference / "data/shopping"))
        )
        return [
            config.service_env.get("MEMORYARENA_WEBSHOP_ITEMS_FILE", str(root / "items_shuffle.json")),
            *[
                str(root / path)
                for path in (
                    "items_ins_v2.json",
                    "domain_data.json",
                    "product_catalog/*.json",
                    "search_engine/indexes-full/*",
                )
            ],
        ]
    if family == "search":
        args = config.tools_config.get("searcher_args")
        if not isinstance(args, dict):
            return ["Search requires tools_config.searcher_args"]
        keys = (
            ("index_path",)
            if config.tools_config.get("searcher_type") == "bm25"
            else ("index_path", "id_map_path", "corpus_path")
        )
        assets = [str(args.get(key, f"Missing {key}")) for key in keys]
        if _uses_tokenizer(config):
            cache = config.service_env.get("HF_HUB_CACHE")
            revision = config.tools_config.get("tokenizer_revision")
            if not cache or not revision:
                assets.append("Search snippets require HF_HUB_CACHE and tools_config.tokenizer_revision")
            else:
                model = Path(cache) / "models--Qwen--Qwen3-0.6B"
                assets.extend([str(model / "refs/main"), str(model / "snapshots" / str(revision))])
        return assets
    return []


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        # A dotted module such as google.genai may have no installed parent.
        return False


def inspect_environment(config: ArenaRuntimeConfig, *, clone: bool = False) -> PreparationReport:
    reference = config.reference.resolve()
    report = PreparationReport(reference=str(reference), revision=config.revision, scene=config.env_name)
    if not reference.exists() and clone:
        reference.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "https://github.com/ZexueHe/MemoryArena.git", str(reference)],
            check=True,
            timeout=300,
        )
        subprocess.run(
            ["git", "-C", str(reference), "checkout", "--detach", config.revision], check=True, timeout=60
        )
    try:
        report.sources = verify_reference(reference, config.revision)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report.missing.append(f"Official source verification failed: {type(exc).__name__}")
    for pattern in required_assets(config):
        files = []
        for name in glob.glob(pattern):
            path = Path(name)
            files.extend([path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()])
        if not files:
            report.missing.append(f"Required asset: {pattern}")
        for path in sorted(files):
            report.assets[str(path.resolve())] = checksum(path)
    modules = ["fastapi", "uvicorn", "anthropic", "datasets"]
    family = arena_scene(config.env_name).family
    if family == "reasoning":
        backend = str(config.env_config.get("backend", "openai")).lower()
        sdk = {
            "openai": "openai",
            "openrouter": "openai",
            "anthropic": "anthropic",
            "gemini": "google.genai",
            "google": "google.genai",
        }.get(backend)
        if sdk is None:
            report.missing.append(f"Unsupported Math/Phys backend: {backend}")
        elif sdk not in modules:
            modules.append(sdk)
    if family == "shopping":
        modules += ["gym", "spacy", "en_core_web_lg", "pyserini", "bs4"]
    if family == "search":
        modules += ["faiss", "fastmcp", "transformers", "torch", "tevatron"]
        if config.tools_config.get("searcher_type") == "bm25":
            modules += ["pyserini"]
        if _uses_tokenizer(config):
            cache = config.service_env.get("HF_HUB_CACHE", "")
            ref = Path(cache) / "models--Qwen--Qwen3-0.6B/refs/main"
            expected = config.tools_config.get("tokenizer_revision")
            if not ref.is_file() or ref.read_text().strip() != expected:
                report.missing.append("Search tokenizer refs/main must match the pinned tokenizer_revision")
            if any(config.service_env.get(key) != "1" for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")):
                report.missing.append("Search snippets require HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1")
    if config.python:
        script = (
            "import importlib.util, json\n"
            "def available(module):\n"
            "    try:\n"
            "        return importlib.util.find_spec(module) is not None\n"
            "    except (ImportError, ValueError):\n"
            "        return False\n"
            f"print(json.dumps([m for m in {modules!r} if not available(m)]))"
        )
        try:
            proc = subprocess.run(
                [config.python, "-c", script], check=True, capture_output=True, text=True, timeout=30
            )
            missing = json.loads(proc.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            missing = ["configured worker Python is unavailable"]
    else:
        missing = [module for module in modules if not _module_available(module)]
    report.missing.extend(f"Worker dependency: {module}" for module in missing)
    report.ready = not report.missing
    return report
