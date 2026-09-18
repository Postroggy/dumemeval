"""Append redacted environment records without rewriting completed actions."""

from pathlib import Path

from dumemeval.artifacts.redaction import Redactor
from dumemeval.models.environment import EnvironmentEvent, EnvironmentEvidence


class EnvironmentJournal:
    """A runtime attempt owns its journal; JSON snapshots remain boundary artifacts."""

    def __init__(self, path: Path, redactor: Redactor) -> None:
        self.path = path
        self.redactor = redactor
        self._started = False
        self._failed = False
        self._evidence_count = 0
        self._event_counts: dict[str, int] = {}

    def flush(
        self, evidence: list[EnvironmentEvidence], histories: dict[str, list[EnvironmentEvent]]
    ) -> None:
        if self._failed:
            raise RuntimeError("Environment journal write failed; start a new runtime attempt")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A partial write cannot safely be retried without duplicating records.
        # Keep the failure latched until a new runtime owns a fresh journal.
        self._failed = True
        with self.path.open("a" if self._started else "w", encoding="utf-8") as handle:
            for record in evidence[self._evidence_count :]:
                handle.write(
                    '{"kind":"evidence","record":' + self.redactor.text(record.model_dump_json()) + "}\n"
                )
            for task_id, events in histories.items():
                for event in events[self._event_counts.get(task_id, 0) :]:
                    handle.write(
                        '{"kind":"lifecycle","record":' + self.redactor.text(event.model_dump_json()) + "}\n"
                    )
        self._evidence_count = len(evidence)
        self._event_counts = {task_id: len(events) for task_id, events in histories.items()}
        self._started = True
        self._failed = False
