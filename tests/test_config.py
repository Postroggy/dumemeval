"""测试：配置加载（pydantic 强校验）。"""

import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.config import load_config

MINIMAL_YAML = """
experiment:
  name: demo
memory:
  name: mem
task:
  sessions:
    - instruction: "s1"
    - instruction: "s2"
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


class TestLoadConfig:
    def test_load_yaml(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "eval.yaml", MINIMAL_YAML)
        cfg = load_config(p)
        assert cfg.experiment.name == "demo"
        assert cfg.experiment.protocol == "memory_session_transfer"  # 默认协议

    def test_load_json(self, tmp_path: Path) -> None:
        import json

        raw = {
            "experiment": {"name": "demo"},
            "memory": {"name": "m"},
            "task": {"sessions": [{"instruction": "s1"}, {"instruction": "s2"}]},
        }
        p = _write(tmp_path, "eval.json", json.dumps(raw))
        assert load_config(p).experiment.name == "demo"

    def test_unsupported_format(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "eval.toml", "x = 1")
        with pytest.raises(ValueError, match="Unsupported config format"):
            load_config(p)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nope.yaml")

    def test_validation_error_on_bad_config(self, tmp_path: Path) -> None:
        """缺 memory 段 → pydantic ValidationError（强校验）。"""
        p = _write(tmp_path, "bad.yaml", "experiment:\n  name: demo\n")
        with pytest.raises(ValidationError):
            load_config(p)

    def test_unknown_adapter_type_raises_on_load(self, tmp_path: Path) -> None:
        """未知 memory.type 在 load_config 失败（不必等到 create_adapter）。"""
        p = _write(
            tmp_path,
            "bad_mem.yaml",
            """
experiment:
  name: demo
memory:
  name: m
  type: not_a_backend
task:
  sessions:
    - instruction: "s1"
    - instruction: "s2"
""",
        )
        with pytest.raises(ValueError, match="Unknown memory adapter type"):
            load_config(p)

    def test_protocol_requires_two_sessions(self, tmp_path: Path) -> None:
        """memory_session_transfer 协议要求 >= 2 sessions。"""
        p = _write(
            tmp_path,
            "one.yaml",
            """
experiment:
  name: demo
  protocol: memory_session_transfer
memory:
  name: m
task:
  sessions:
    - instruction: "s1"
""",
        )
        with pytest.raises(ValidationError, match="requires >= 2 sessions"):
            load_config(p)

    def test_test_only_requires_no_inject(self, tmp_path: Path) -> None:
        """test_only 协议要求所有 session 不注入 memory。"""
        p = _write(
            tmp_path,
            "test_only.yaml",
            """
experiment:
  name: demo
  protocol: test_only
memory:
  name: m
task:
  sessions:
    - instruction: "s1"
""",
        )
        with pytest.raises(ValidationError, match="memory_inject=false"):
            load_config(p)

    def test_test_only_benchmark_skips_placeholder_validation(self, tmp_path: Path) -> None:
        """test_only × benchmark：占位 session 默认 memory_inject 也能加载。

        benchmark 路径的真实校验在 cli._build_tasks（适配器产物归一化后逐任务），
        加载期占位 sessions 不该挡路（适配器产物硬编码 memory_inject=True）。
        """
        p = _write(
            tmp_path,
            "test_only_bench.yaml",
            """
experiment:
  name: demo
  protocol: test_only
memory:
  name: m
task:
  benchmark: locomo
  data:
    type: local
    path: data.json
  sessions:
    - instruction: "占位"
      placeholder: true
""",
        )
        cfg = load_config(p)  # 不抛 ValidationError
        assert cfg.protocol_instance.name == "test_only"
        assert cfg.task.benchmark == "locomo"

    def test_benchmark_without_data_still_validates_placeholders(self, tmp_path: Path) -> None:
        """benchmark 缺 data：占位即最终 sessions（无构建兜底），加载期仍校验。"""
        p = _write(
            tmp_path,
            "bench_no_data.yaml",
            """
experiment:
  name: demo
  protocol: test_only
memory:
  name: m
task:
  benchmark: locomo
  sessions:
    - instruction: "s1"
""",
        )
        with pytest.raises(ValidationError, match="memory_inject=false"):
            load_config(p)


class TestPlaceholderSemantics:
    """sessions 占位语义：benchmark + data 必须显式标 placeholder；非 benchmark 禁止。"""

    def test_benchmark_data_requires_placeholder(self, tmp_path: Path) -> None:
        """benchmark + data 但 sessions 没标 placeholder → 报错（防止误改占位指令）。"""
        p = _write(
            tmp_path,
            "bench_missing_ph.yaml",
            """
experiment:
  name: demo
memory:
  name: m
task:
  benchmark: locomo
  data:
    type: local
    name: locomo_smoke
  sessions:
    - instruction: "（由 benchmark 适配器生成）"
""",
        )
        with pytest.raises(ValidationError, match="placeholder: true"):
            load_config(p)

    def test_non_benchmark_forbids_placeholder(self, tmp_path: Path) -> None:
        """非 benchmark 路径没有适配器生成 sessions，placeholder 无意义 → 报错。"""
        p = _write(
            tmp_path,
            "nonbench_ph.yaml",
            """
experiment:
  name: demo
memory:
  name: m
task:
  sessions:
    - instruction: "s1"
      placeholder: true
    - instruction: "s2"
""",
        )
        with pytest.raises(ValidationError, match="只用于 benchmark"):
            load_config(p)

    def test_benchmark_data_placeholder_ok(self, tmp_path: Path) -> None:
        """显式标 placeholder: true 的 benchmark 配置正常加载。"""
        p = _write(
            tmp_path,
            "bench_ph_ok.yaml",
            """
experiment:
  name: demo
memory:
  name: m
task:
  benchmark: locomo
  data:
    type: local
    path: data.json
  sessions:
    - instruction: "（由 benchmark 适配器生成）"
      placeholder: true
    - instruction: "（由 benchmark 适配器生成）"
      placeholder: true
""",
        )
        cfg = load_config(p)
        assert all(s.placeholder for s in cfg.task.sessions)


class TestMemoryConfigTyped:
    """内置 adapter 的 memory.config 类型化校验（未知键加载期报错）。"""

    def _cfg(self, tmp_path: Path, memory_block: str) -> Path:
        return _write(
            tmp_path,
            "mem_cfg.yaml",
            f"""
experiment:
  name: demo
memory:
  name: m
{memory_block}task:
  sessions:
    - instruction: "s1"
    - instruction: "s2"
""",
        )

    def test_hermes_unknown_key_rejected(self, tmp_path: Path) -> None:
        p = self._cfg(
            tmp_path,
            "  type: hermes_builtin\n  config:\n    targets: [memory]\n    memory_limt: 999\n",  # 拼写错误
        )
        with pytest.raises(ValidationError, match="memory_limt"):
            load_config(p)

    def test_hermes_valid_config_ok(self, tmp_path: Path) -> None:
        p = self._cfg(
            tmp_path,
            "  type: hermes_builtin\n"
            "  config:\n"
            "    targets: [memory, user]\n"
            "    memory_limit: 2200\n"
            "    model: deepseek\n",
        )
        cfg = load_config(p)
        assert cfg.memory.type == "hermes_builtin"
        assert cfg.memory.config["memory_limit"] == 2200

    def test_everos_unknown_key_rejected(self, tmp_path: Path) -> None:
        p = self._cfg(
            tmp_path,
            "  type: everos\n  config:\n    top_k: 10\n    topk: 5\n",  # 拼写错误
        )
        with pytest.raises(ValidationError, match="topk"):
            load_config(p)

    def test_everos_bad_method_rejected(self, tmp_path: Path) -> None:
        p = self._cfg(
            tmp_path,
            "  type: everos\n  config:\n    method: bogus\n",
        )
        with pytest.raises(ValidationError):
            load_config(p)

    def test_community_adapter_config_free(self, tmp_path: Path) -> None:
        """不在内置注册表的 adapter（社区）config 保持开放 dict，不校验。"""
        p = self._cfg(
            tmp_path,
            "  type: mem0\n  config:\n    anything: goes\n    top_k: 3\n",
        )
        # mem0 未注册 → load_config 会报 Unknown adapter，但那是注册表检查，
        # 不是 config 类型化——确认错误信息与 config 无关
        with pytest.raises(ValueError, match="Unknown memory adapter type"):
            load_config(p)


class TestJudgePromptSync:
    """JudgeSpec.prompt 与 verifier 注册表同步（core 不能 import verifier，用测试锁）。"""

    def test_prompt_choices_match_verifier_registry(self) -> None:
        from typing import get_args

        from dumemeval.core.config import JudgeSpec
        from dumemeval.verifier.llm import LLMJudgeVerifier

        config_prompts = set(get_args(JudgeSpec.model_fields["prompt"].annotation))
        assert config_prompts == set(LLMJudgeVerifier._PROMPT_TEMPLATES)


class TestEnvTemplates:
    def test_env_template_resolution(self, tmp_path: Path, monkeypatch: Any) -> None:
        """${VAR} 模板从宿主 env 解析。"""
        monkeypatch.setenv("DUMEVAL_TEST_KEY", "secret-value")
        p = _write(
            tmp_path,
            "env.yaml",
            """
experiment:
  name: demo
memory:
  name: m
task:
  sessions:
    - instruction: "s1"
    - instruction: "s2"
execution:
  engine: mock
  environment:
    env:
      TEST_KEY: ${DUMEVAL_TEST_KEY}
""",
        )
        cfg = load_config(p)
        assert cfg.execution.environment.env["TEST_KEY"] == "secret-value"

    def test_env_template_default(self, tmp_path: Path) -> None:
        """${VAR:-default} 缺失时用默认值。"""
        p = _write(
            tmp_path,
            "env_default.yaml",
            """
experiment:
  name: demo
memory:
  name: m
task:
  sessions:
    - instruction: "s1"
    - instruction: "s2"
execution:
  environment:
    env:
      MISSING: ${NONEXISTENT_VAR_XYZ:-fallback}
""",
        )
        cfg = load_config(p)
        assert cfg.execution.environment.env["MISSING"] == "fallback"

    def test_env_template_missing_raises(self, tmp_path: Path) -> None:
        """${VAR} 缺失且无默认 → 报错（避免静默空值）。"""
        p = _write(
            tmp_path,
            "env_missing.yaml",
            """
experiment:
  name: demo
memory:
  name: m
task:
  sessions:
    - instruction: "s1"
    - instruction: "s2"
execution:
  environment:
    env:
      BAD: ${NONEXISTENT_VAR_XYZ}
""",
        )
        with pytest.raises(ValueError, match="NONEXISTENT_VAR_XYZ"):
            load_config(p)

    def test_does_not_read_home_claude_settings(self, tmp_path: Path, monkeypatch: Any) -> None:
        """load_config 只认进程环境变量，不扫 ~/.claude/settings.json。"""
        monkeypatch.delenv("DUMEVAL_TEST_KEY", raising=False)
        p = _write(
            tmp_path,
            "needs_env.yaml",
            """
experiment:
  name: demo
memory:
  name: m
task:
  sessions:
    - instruction: "s1"
    - instruction: "s2"
execution:
  environment:
    env:
      TEST_KEY: ${DUMEVAL_TEST_KEY}
""",
        )
        with pytest.raises(ValueError, match="DUMEVAL_TEST_KEY"):
            load_config(p)


class TestToEvalTask:
    def test_judge_robustness_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(_write(tmp_path, "eval.yaml", MINIMAL_YAML))
        assert cfg.judging.num_runs == 1
        assert cfg.judging.max_retries == 3
        assert cfg.judging.skip_failed is False
        assert cfg.judging.save_model_input is False
        assert cfg.execution.resume is True

    def test_judge_robustness_overrides(self, tmp_path: Path) -> None:
        p = _write(
            tmp_path,
            "robust.yaml",
            MINIMAL_YAML
            + """
judging:
  type: llm_judge
  num_runs: 3
  max_retries: 2
  skip_failed: true
  save_model_input: true
execution:
  resume: false
""",
        )
        cfg = load_config(p)
        assert cfg.judging.num_runs == 3
        assert cfg.judging.max_retries == 2
        assert cfg.judging.skip_failed is True
        assert cfg.judging.save_model_input is True
        assert cfg.execution.resume is False

    def test_to_eval_task(self, tmp_path: Path) -> None:
        """ExperimentConfig → EvalTask 转换。"""
        p = _write(tmp_path, "eval.yaml", MINIMAL_YAML)
        cfg = load_config(p)
        task = cfg.to_eval_task()
        assert task.name == "demo"
        assert len(task.sessions) == 2
        assert task.sessions[0].instruction == "s1"
        assert task.sessions[0].id == 1
