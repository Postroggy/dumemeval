"""Credential redaction shared by execution logs and exported reports."""

from __future__ import annotations

import json
from pathlib import Path


def _secret_field(key: str) -> bool:
    upper = key.upper()
    if upper == "API_KEY_ENV":
        return False  # This names a credential variable; it is not its value.
    return (
        any(marker in upper for marker in ("KEY", "SECRET", "PASSWORD", "AUTH"))
        or upper == "TOKEN"
        or upper.endswith("_TOKEN")
    )


def redact_config(obj: object) -> object:
    """Preserve public config values while replacing credential fields."""
    if isinstance(obj, dict):
        return {
            str(key): "***" if _secret_field(str(key)) else redact_config(value) for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [redact_config(item) for item in obj]
    return obj


class Redactor:
    """Replace known credential values, including their JSON-escaped spellings."""

    def __init__(self, environment: dict[str, str]) -> None:
        self.secrets = sorted(
            {v for k, v in environment.items() if v and _secret_field(k)},
            key=len,
            reverse=True,
        )

    def text(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(json.dumps(secret)[1:-1], "[REDACTED]").replace(secret, "[REDACTED]")
        return value

    def tree(self, root: Path) -> None:
        """Sanitize owned UTF-8 artifacts; leave binary attachments intact."""
        if not root.exists():
            return
        resolved = root.resolve()
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(resolved):
                continue
            try:
                original = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue
            sanitized = self.text(original)
            if sanitized != original:
                path.write_bytes(sanitized.encode("utf-8"))
