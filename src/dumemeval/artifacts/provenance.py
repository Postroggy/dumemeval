"""实验溯源：git / 脱敏配置 / 复现命令。

报告要能被引用，必须能回答：哪次代码、哪份配置、怎么重跑、是否 mock。
模型在 models/run.py（GitSnapshot / RunProvenance）；这里只放采集与渲染。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from ..core.config import ExperimentConfig
from ..models import GitSnapshot, RunProvenance

_SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "AUTH")

__all__ = [
    "GitSnapshot",
    "RunProvenance",
    "collect_git",
    "derive_run_id",
    "provenance_markdown",
    "redact_config",
    "reproduce_command",
    "snapshot_run",
]


def derive_run_id(cfg: ExperimentConfig) -> str:
    """由实验变量派生稳定 run_id（可复现身份，不参与 compare 准入）。

    变量：benchmark + data.name + protocol + memory.type + memory_instruction +
    agent.runtime。同一 config 在任何机器/任何 output 目录跑出同一 run_id；
    换实验变量（如换 memory 后端）→ 新 run_id。sha256 前缀保证跨字段唯一。
    """
    parts = [
        cfg.task.benchmark or "",
        (cfg.task.data.name or "") if cfg.task.data else "",
        cfg.experiment.protocol,
        cfg.memory.type,
        cfg.task.memory_instruction,
        cfg.agent.runtime,
    ]
    key = "|".join(parts)
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    slug = "-".join(p.replace("/", "_") or "x" for p in parts)
    return f"{slug}-{digest}"


def redact_config(obj: object) -> object:
    """递归脱敏：键名含 KEY/SECRET/TOKEN/PASSWORD/AUTH 的值改为 ***。"""
    if isinstance(obj, dict):
        out: dict[str, object] = {}
        for key, value in obj.items():
            if any(marker in str(key).upper() for marker in _SECRET_MARKERS):
                out[str(key)] = "***"
            else:
                out[str(key)] = redact_config(value)
        return out
    if isinstance(obj, list):
        return [redact_config(item) for item in obj]
    return obj


def collect_git(cwd: Path | None = None) -> GitSnapshot:
    """读当前仓库 HEAD；失败则空快照（不抛）。"""
    root = cwd or Path.cwd()

    def _run(args: list[str]) -> str | None:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

    commit = _run(["rev-parse", "--short", "HEAD"])
    if commit is None:
        return GitSnapshot()
    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    status = _run(["status", "--porcelain"])
    return GitSnapshot(commit=commit, branch=branch, dirty=bool(status))


def reproduce_command(*, config_path: str, output_dir: str, mock: bool) -> str:
    """生成可复制的 CLI 复现命令。"""
    parts = [
        ".venv/bin/python -m dumemeval run",
        f"--config {config_path}",
        f"--output {output_dir}",
    ]
    if mock:
        parts.append("--mock")
    return " ".join(parts)


def snapshot_run(
    cfg: ExperimentConfig,
    *,
    output_dir: str | Path,
    config_path: str,
    mock: bool,
    n_concurrent: int = 1,
) -> RunProvenance:
    """落盘 ``experiment_config.json``（脱敏配置 + git + 复现命令）。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    provenance = RunProvenance(
        run_id=derive_run_id(cfg),
        mock=mock,
        reproduce=reproduce_command(config_path=config_path, output_dir=str(out), mock=mock),
        git=collect_git(),
        n_concurrent=n_concurrent,
        judging_type=cfg.judging.type,
        judging_model=cfg.judging.model,
        judging_num_runs=cfg.judging.num_runs,
        judging_skip_failed=cfg.judging.skip_failed,
        config_path=config_path,
        output_dir=str(out),
    )
    payload = {
        "provenance": provenance.model_dump(),
        "config": redact_config(cfg.model_dump()),
    }
    (out / "experiment_config.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return provenance


def provenance_markdown(provenance: RunProvenance, *, heading: bool = True) -> list[str]:
    """报告 / summary 共用的 mock 横幅 + 复现命令 + git/judge 行。"""
    lines: list[str] = []
    if provenance.mock:
        lines += [
            "> **mock 模式：observation 是占位文本，指标仅验证编排，不可引用为实验结果。**",
            "",
        ]
    if heading:
        lines += ["## Reproduce", ""]
    lines += ["```bash", provenance.reproduce, "```", ""]
    git = provenance.git
    git_line = git.commit or "n/a"
    if git.branch:
        git_line += f" ({git.branch})"
    if git.dirty:
        git_line += " dirty"
    lines += [
        f"- git: `{git_line}`",
        f"- judging: type={provenance.judging_type} model={provenance.judging_model or 'n/a'} "
        f"num_runs={provenance.judging_num_runs} skip_failed={provenance.judging_skip_failed}",
        "",
    ]
    return lines
