"""Harbor task 目录生成器。

职责边界：**只做「SessionSpec → Harbor task 目录」的翻译**，不做判分、
不做环境策略。判分在 host 的 `metrics/`；环境构建参数来自 `EnvironmentSpec`。

生成的目录结构（Harbor 约定）：
    <task_dir>/
    ├── instruction.md      # agent 的任务指令（SessionSpec.instruction 原文）
    ├── task.toml           # 资源与超时（来自 execution.environment）
    ├── tests/
    │   ├── test.sh         # Harbor verifier 入口
    │   ├── verifier.py     # 默认 no-op（判分在 host）；显式配置 verifier 时才生成
    │   └── ground_truth.txt
    └── environment/
        └── Dockerfile      # 按 EnvironmentSpec 拼接；dockerfile 字段可整体接管

设计要点：
- **默认 no-op verifier**：评测结论在 host 算（trajectory → metrics/）。此前在
  容器里生成简化 verifier，空 ground_truth 时 `"" in answers` 恒真 → reward 恒
  1.0 → utility.success_rate 恒 1.0（假信号）。显式配置 `session.verifier`
  时才生成真实判分（用户主动要求容器内判分）。
- **默认最小镜像**：不改镜像源、不预装 agent（Harbor 的 BaseInstalledAgent 负责
  安装）。镜像源 / 预装是国内/内网用户的地域配置，不是框架默认。
- **memory 不进镜像**：统一走运行时挂载（`memory_mounts` 契约），build 期 COPY
  会被挂载覆盖，是死代码。
"""

from __future__ import annotations

from pathlib import Path

from ..core.config import EnvironmentSpec
from ..models import SessionSpec

_NOOP_VERIFIER = '''"""No-op verifier: DuMemEval scores on the host.

Container scoring was removed: the generated verifier used to mark every
session as successful (`"" in answers` with empty ground truth), producing
fake utility.success_rate=1.0. Real scoring happens in dumemeval.metrics/
(on the host) from the agent trajectory.
"""
import json
from pathlib import Path

REWARD_PATH = Path("/logs/verifier/reward.json")

def main():
    REWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REWARD_PATH.write_text(json.dumps({
        "total": 0.0,
        "scored_on_host": 1.0,
    }))

if __name__ == "__main__":
    main()
'''

_RULE_VERIFIER = '''"""Rule verifier (explicitly configured via session.verifier)."""
import json
from pathlib import Path

GROUND_TRUTH_PATH = Path("/tests/ground_truth.txt")
ANSWERS_PATH = Path("/workspace/answers.txt")
REWARD_PATH = Path("/logs/verifier/reward.json")

def main():
    gt = GROUND_TRUTH_PATH.read_text().strip()
    if not gt:
        raise SystemExit("empty ground truth: rule verifier cannot score; "
                         "leave session.verifier unset to score on host")
    answers = ANSWERS_PATH.read_text().strip() if ANSWERS_PATH.exists() else ""
    ok = gt.lower() in answers.lower()
    REWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REWARD_PATH.write_text(json.dumps({
        "total": 1.0 if ok else 0.0,
        "answers_hit": 1.0 if ok else 0.0,
    }))
    print(f"rule verifier: {'PASS' if ok else 'FAIL'}")

if __name__ == "__main__":
    main()
'''

_LLM_JUDGE_VERIFIER = '''"""LLM judge verifier (explicitly configured via session.verifier)."""
import json
import os
from pathlib import Path

GROUND_TRUTH_PATH = Path("/tests/ground_truth.txt")
ANSWERS_PATH = Path("/workspace/answers.txt")
REWARD_PATH = Path("/logs/verifier/reward.json")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-4o-mini")
JUDGE_PROMPT = (
    "You are an expert grader. Judge if the response matches the ground truth.\\n"
    "Ground truth: {ground_truth}\\nResponse: {response}\\n"
    'Return CORRECT or WRONG as JSON: {{"label": "CORRECT" or "WRONG"}}'
)

def main():
    gt = GROUND_TRUTH_PATH.read_text().strip()
    if not gt:
        raise SystemExit("empty ground truth: llm judge verifier cannot score; "
                         "leave session.verifier unset to score on host")
    answers = ANSWERS_PATH.read_text().strip() if ANSWERS_PATH.exists() else ""

    from openai import OpenAI
    client = OpenAI()
    resp = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert grader."},
            {"role": "user", "content": JUDGE_PROMPT.format(ground_truth=gt, response=answers)},
        ],
        temperature=0,
        max_tokens=512,
    )
    raw = resp.choices[0].message.content or ""
    ok = "CORRECT" in raw.upper() or "PASS" in raw.upper()
    REWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REWARD_PATH.write_text(json.dumps({
        "total": 1.0 if ok else 0.0,
        "judge_score": 1.0 if ok else 0.0,
    }))
    print(f"llm judge verifier: {'PASS' if ok else 'FAIL'}")

if __name__ == "__main__":
    main()
'''


class TaskDirGenerator:
    """生成 Harbor task 目录（只做翻译；判分在 host，环境参数来自配置）。"""

    def __init__(
        self,
        tasks_root: str | Path = "tasks_generated",
        env_spec: EnvironmentSpec | None = None,
    ):
        self.tasks_root = Path(tasks_root)
        self.env_spec = env_spec or EnvironmentSpec()

    def generate(
        self,
        session: SessionSpec,
        task_name: str = "dumemeval_task",
        instruction_suffix: str = "",
    ) -> Path:
        """为单个 session 生成 task 目录，返回目录路径。

        instruction_suffix: lifecycle 层按 memory_instruction / task_environment
        组装的补充说明（原文之后追加；空串 = 纯原文）。
        """
        task_dir = self.tasks_root / f"{task_name}__session_{session.id}"
        (task_dir / "tests").mkdir(parents=True, exist_ok=True)
        (task_dir / "environment").mkdir(parents=True, exist_ok=True)

        from ..core.instructions import render_instruction

        instruction = render_instruction(session.instruction, instruction_suffix)
        (task_dir / "instruction.md").write_text(instruction, encoding="utf-8", newline="\n")
        self._write_task_toml(task_dir, session)
        self._write_verifier(task_dir, session)
        self._write_dockerfile(task_dir)

        return task_dir

    # ── task.toml ─────────────────────────────────────────────────────────

    def _write_task_toml(self, task_dir: Path, session: SessionSpec) -> None:
        env = self.env_spec
        verifier = session.verifier
        vtimeout = verifier.timeout_sec if verifier else 600.0

        toml = f"""schema_version = "1.0"

[task]
name = "dumemeval/task__session_{session.id}"
description = "DuMemEval session {session.id}"

[verifier]
timeout_sec = {vtimeout}

[agent]
timeout_sec = {env.agent_timeout_sec}

[environment]
build_timeout_sec = 600.0
cpus = {env.cpus}
memory_mb = {env.memory_mb}
storage_mb = {env.storage_mb}
"""
        (task_dir / "task.toml").write_text(toml)

    # ── tests/ ────────────────────────────────────────────────────────────

    def _write_verifier(self, task_dir: Path, session: SessionSpec) -> None:
        """默认 no-op（判分在 host）；显式配置 session.verifier 才生成真实判分。"""
        tests_dir = task_dir / "tests"
        verifier = session.verifier

        gt_text = verifier.ground_truth if verifier else ""
        (tests_dir / "ground_truth.txt").write_text(gt_text)

        if verifier is None:
            verifier_py = _NOOP_VERIFIER
        elif verifier.type == "llm_judge":
            verifier_py = _LLM_JUDGE_VERIFIER
        else:
            verifier_py = _RULE_VERIFIER

        (tests_dir / "verifier.py").write_text(verifier_py)
        (tests_dir / "test.sh").write_text(
            "#!/bin/bash\nset -Eeuo pipefail\nmkdir -p /logs/verifier\npython3 /tests/verifier.py\n"
        )
        (tests_dir / "test.sh").chmod(0o755)

    # ── environment/Dockerfile ────────────────────────────────────────────

    def _write_dockerfile(self, task_dir: Path) -> None:
        """按 EnvironmentSpec 生成 Dockerfile；`dockerfile` 字段整体接管。"""
        env = self.env_spec

        if env.dockerfile:
            (task_dir / "environment" / "Dockerfile").write_text(Path(env.dockerfile).read_text())
            return

        base = env.docker_image or env.base_image
        lines = [f"FROM {base}", "WORKDIR /workspace"]

        if env.apt_mirror:
            lines.append(_apt_mirror_layer(env.apt_mirror))
        if env.apt_packages:
            pkgs = " ".join(env.apt_packages)
            lines.append(
                f"RUN apt-get update && apt-get install -y --no-install-recommends {pkgs} "
                "&& rm -rf /var/lib/apt/lists/*"
            )
        if env.pip_index_url:
            lines.append(f"RUN pip config set global.index-url {env.pip_index_url}")
        if env.pip_packages:
            pkgs = " ".join(env.pip_packages)
            lines.append(f"RUN pip install --no-cache-dir {pkgs}")
        for command in env.setup_commands:
            lines.append(f"RUN {command}")

        (task_dir / "environment" / "Dockerfile").write_text("\n".join(lines) + "\n")


def _apt_mirror_layer(mirror: str) -> str:
    """把 Debian 源域名替换为指定镜像（兼容 deb822 与旧版 sources.list）。"""
    return (
        "RUN sed -i "
        f"'s|deb.debian.org|{mirror}|g; "
        f"s|security.debian.org|{mirror}|g; "
        f"s|deb.debian.org/debian-security|{mirror}/debian-security|g' "
        "/etc/apt/sources.list.d/debian.sources 2>/dev/null || "
        "sed -i "
        f"'s|deb.debian.org|{mirror}|g; "
        f"s|security.debian.org|{mirror}|g' "
        "/etc/apt/sources.list 2>/dev/null || true"
    )
