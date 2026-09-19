"""One rendering contract for execution inputs and their recorded fingerprints."""

import hashlib


def render_instruction(instruction: str, suffix: str = "") -> str:
    """Render the exact UTF-8 task instruction handed to the executor."""
    return f"{instruction}\n{suffix}" if suffix else instruction


def instruction_digest(instruction: str, suffix: str = "") -> str:
    """Hash the rendered instruction without storing potentially sensitive text."""
    return hashlib.sha256(render_instruction(instruction, suffix).encode("utf-8")).hexdigest()
