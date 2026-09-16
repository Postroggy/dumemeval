"""Durable benchmark scoring attempts, independent of benchmark and runtime."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..artifacts.controls import digest, observed_controls, runtime_versions
from ..artifacts.redaction import Redactor, redact_config
from ..evaluation.scorer import BenchmarkScorer
from ..metrics.core.base import MetricInput
from ..models import BenchmarkResult


class ScoringCheckpointError(RuntimeError):
    """A previous attempt cannot safely be replayed automatically."""


def scoring_context(judge: dict[str, Any], dataset: object, output_dir: Path) -> dict[str, Any]:
    """Bind scores to the judge, source/data versions and observed environment."""
    root = Path(__file__).resolve().parents[1]
    sources = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for module in ("evaluation", "metrics", "verifier", "models", "benchmarks")
        for path in sorted((root / module).rglob("*.py"))
    }
    for relative in ("pipeline/scoring.py", "core/retry.py", "core/config.py"):
        sources[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    return {
        "judge": redact_config(judge),
        "judge_environment": {
            name: os.environ.get(name)
            for name in (
                "JUDGE_MODEL",
                "JUDGE_BASE_URL",
                "JUDGE_API_KEY_ENV",
                "OPENAI_BASE_URL",
                "ANTHROPIC_BASE_URL",
                "OPENAI_ORG_ID",
                "OPENAI_PROJECT_ID",
            )
        },
        "dataset": redact_config(dataset),
        "sources": digest(sources),
        "packages": runtime_versions(),
        "observed_environment": observed_controls(output_dir)["observed_environment"],
    }


class CheckpointedScorer(BenchmarkScorer):
    """Reserve before scoring; reuse a completed result or stop on uncertainty."""

    def __init__(
        self, scorer: BenchmarkScorer, directory: Path, context: dict[str, Any], redactor: Redactor
    ) -> None:
        self.scorer = scorer
        self.directory = directory
        self.context = context
        self.redactor = redactor

    def score(self, inp: MetricInput) -> BenchmarkResult:
        identity = digest({"schema": 1, "context": self.context, "input": inp.model_dump(mode="json")})
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{identity}.json"
        # Exclusive creation arbitrates concurrent finalizers before any judge call.
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump({"schema": 1, "input_digest": identity, "status": "pending"}, handle)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            return self._completed(path, identity)

        result = self.scorer.score(inp)
        # Sanitize first, so the original return value and a cache hit are identical.
        result = BenchmarkResult.model_validate_json(self.redactor.text(result.model_dump_json()))
        data = result.model_dump(mode="json")
        record = {
            "schema": 1,
            "input_digest": identity,
            "status": "completed",
            "result": data,
            "result_digest": digest(data),
        }
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        return result

    def _completed(self, path: Path, identity: str) -> BenchmarkResult:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (
                record["schema"] != 1
                or record["input_digest"] != identity
                or record["status"] != "completed"
                or record["result_digest"] != digest(record["result"])
            ):
                raise ValueError("Incomplete or mismatched checkpoint")
            return BenchmarkResult.model_validate(record["result"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ScoringCheckpointError(
                f"Scoring checkpoint is pending or invalid: {path}. No judge was called. "
                "Inspect the previous attempt before explicitly starting a new run/output directory."
            ) from exc
