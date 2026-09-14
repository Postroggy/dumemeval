"""测试：Harbor task 目录生成（适配 vs 判分边界）。

背景：TaskDirGenerator 曾在容器里生成一套简化 verifier（空 ground_truth 时恒
PASS → utility.success_rate 恒 1.0），并硬编码清华镜像源 / claude 安装 /
COPY memory。现契约：容器只做适配，判分在 host（metrics/）；环境可配置。
"""

from __future__ import annotations

from pathlib import Path

from dumemeval.core.config import EnvironmentSpec
from dumemeval.execution.task_dir import TaskDirGenerator
from dumemeval.models import SessionSpec, VerifierSpec


def _session() -> SessionSpec:
    return SessionSpec(id=1, instruction="do the task")


class TestDefaultVerifierIsNoop:
    """benchmark 路径下 session.verifier=None：容器不得自行判分。"""

    def test_default_verifier_is_noop(self, tmp_path: Path) -> None:
        gen = TaskDirGenerator(tasks_root=tmp_path)
        task_dir = gen.generate(_session())

        verifier_py = (task_dir / "tests" / "verifier.py").read_text()
        assert "answers.txt" not in verifier_py, "no-op verifier 不应读 agent 产出"
        assert "scored_on_host" in verifier_py, "必须显式声明判分在 host"
        assert "note" not in verifier_py, "Harbor VerifierResult.rewards 只接受数字，不能写 note 字符串"

    def test_noop_reward_is_zero_not_one(self, tmp_path: Path) -> None:
        """no-op reward 必须是 0.0——写 1.0 会把「跑完了」伪装成「做对了」。"""
        gen = TaskDirGenerator(tasks_root=tmp_path)
        task_dir = gen.generate(_session())
        assert '"total": 0.0' in (task_dir / "tests" / "verifier.py").read_text()

    def test_explicit_verifier_still_generates_real_scoring(self, tmp_path: Path) -> None:
        """用户显式配置 session.verifier 时才生成真实判分。"""
        gen = TaskDirGenerator(tasks_root=tmp_path)
        session = SessionSpec(
            id=1,
            instruction="do",
            verifier=VerifierSpec(type="rule", ground_truth="latte"),
        )
        task_dir = gen.generate(session)
        verifier_py = (task_dir / "tests" / "verifier.py").read_text()
        assert "answers.txt" in verifier_py
        assert "latte" in (task_dir / "tests" / "ground_truth.txt").read_text()


class TestDockerfileConfigurable:
    """默认最小镜像；镜像源 / 预装 / 整份 Dockerfile 均可配置。"""

    def test_default_is_minimal_no_mirrors_no_claude(self, tmp_path: Path) -> None:
        gen = TaskDirGenerator(tasks_root=tmp_path)
        dockerfile = (gen.generate(_session()) / "environment" / "Dockerfile").read_text()

        assert "tuna.tsinghua" not in dockerfile, "镜像源不应是默认值（地域优化属于用户配置）"
        assert "downloads.claude.ai" not in dockerfile, "agent 安装是 Harbor 的职责"
        assert "COPY memory/" not in dockerfile, "memory 走运行时挂载，不走 build 期 COPY"
        assert "FROM python:3.13-slim" in dockerfile

    def test_mirrors_and_packages_via_config(self, tmp_path: Path) -> None:
        env = EnvironmentSpec(
            apt_mirror="mirrors.tuna.tsinghua.edu.cn",
            pip_index_url="https://pypi.tuna.tsinghua.edu.cn/simple",
            apt_packages=["curl", "git"],
            pip_packages=["openai"],
            setup_commands=["curl -fsSL https://example.com/install.sh | bash"],
        )
        gen = TaskDirGenerator(tasks_root=tmp_path, env_spec=env)
        dockerfile = (gen.generate(_session()) / "environment" / "Dockerfile").read_text()

        assert "mirrors.tuna.tsinghua.edu.cn" in dockerfile
        assert "pypi.tuna.tsinghua.edu.cn/simple" in dockerfile
        assert "apt-get install -y --no-install-recommends curl git" in dockerfile
        assert "pip install --no-cache-dir openai" in dockerfile
        assert "curl -fsSL https://example.com/install.sh | bash" in dockerfile

    def test_dockerfile_field_takes_over_entirely(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom.Dockerfile"
        custom.write_text("FROM scratch\nCOPY hello.txt /\n")
        env = EnvironmentSpec(dockerfile=str(custom))
        gen = TaskDirGenerator(tasks_root=tmp_path, env_spec=env)
        generated = (gen.generate(_session()) / "environment" / "Dockerfile").read_text()
        assert generated == "FROM scratch\nCOPY hello.txt /\n"

    def test_docker_image_still_used_as_base(self, tmp_path: Path) -> None:
        env = EnvironmentSpec(docker_image="dumeval-hermes:latest")
        gen = TaskDirGenerator(tasks_root=tmp_path, env_spec=env)
        dockerfile = (gen.generate(_session()) / "environment" / "Dockerfile").read_text()
        assert dockerfile.startswith("FROM dumeval-hermes:latest")


class TestResourcesConfigurable:
    def test_task_toml_resources_from_env_spec(self, tmp_path: Path) -> None:
        env = EnvironmentSpec(cpus=4, memory_mb=8192, storage_mb=20480, agent_timeout_sec=3600.0)
        gen = TaskDirGenerator(tasks_root=tmp_path, env_spec=env)
        toml = (gen.generate(_session()) / "task.toml").read_text()
        assert "cpus = 4" in toml
        assert "memory_mb = 8192" in toml
        assert "storage_mb = 20480" in toml
        assert "timeout_sec = 3600.0" in toml

    def test_defaults(self, tmp_path: Path) -> None:
        gen = TaskDirGenerator(tasks_root=tmp_path)
        toml = (gen.generate(_session()) / "task.toml").read_text()
        assert "cpus = 1" in toml
        assert "memory_mb = 2048" in toml
