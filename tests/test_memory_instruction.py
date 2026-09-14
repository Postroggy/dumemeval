"""测试：memory_instruction 在 benchmark 构建路径的回填与协议归一化。

背景（见 docs/lifecycle/memory-instruction-modes.md）：
- benchmark 适配器按数据集口径构建任务，不知道 memory_instruction /
  task_environment 这些评测设计层的选择——回填发生在 cli._build_tasks
- test_only 协议经 normalize_sessions 强制关闭注入，兼容适配器硬编码的
  memory_inject=True
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.cli.run import _build_tasks
from dumemeval.config import load_config

LOCOMO_MINI = Path(__file__).parent.parent / "examples" / "data" / "locomo_mini.json"


def _bench_config(
    tmp_path: Path, name: str, task_extra: str, protocol: str = "memory_session_transfer"
) -> Path:
    p = tmp_path / name
    p.write_text(
        f"""
experiment:
  name: bench-{name}
  protocol: {protocol}
memory:
  name: m
  type: directory
task:
  benchmark: locomo
  benchmark_options:
    subset: 1
    max_questions: 2
  data:
    type: local
    path: {LOCOMO_MINI}
  sessions:
    - instruction: "占位"
      placeholder: true
{task_extra}judging:
  type: rule
execution:
  engine: mock
"""
    )
    return p


class TestBenchmarkBackfill:
    """配置级字段回填到适配器产物（memory_instruction / task_environment）。"""

    def test_backfill_proactive(self, tmp_path: Path) -> None:
        cfg = load_config(_bench_config(tmp_path, "proactive.yaml", "  memory_instruction: proactive\n"))
        tasks = _build_tasks(cfg)
        assert tasks, "locomo_mini 应构建出任务"
        assert all(t.memory_instruction == "proactive" for t in tasks)
        # 回填只碰设计层字段，不覆盖适配器按官方口径填好的内容
        first = tasks[0]
        assert first.memory_ground_truth, "locomo 适配器填的 ground truth 应保留"
        assert first.benchmark == "locomo"
        assert first.data.get("sample_id") == "example_conv_0"

    def test_backfill_none_default(self, tmp_path: Path) -> None:
        """默认 none 回填是幂等的（适配器产物本来就是 none）。"""
        cfg = load_config(_bench_config(tmp_path, "default.yaml", ""))
        tasks = _build_tasks(cfg)
        assert all(t.memory_instruction == "none" for t in tasks)

    def test_backfill_task_environment(self, tmp_path: Path) -> None:
        cfg = load_config(
            _bench_config(
                tmp_path,
                "env.yaml",
                "  memory_instruction: location\n"
                "  task_environment:\n"
                "    type: http\n"
                "    base_url: http://localhost:8080\n",
            )
        )
        tasks = _build_tasks(cfg)
        assert tasks
        assert all(
            t.task_environment == {"type": "http", "base_url": "http://localhost:8080", "config": {}}
            for t in tasks
        )

    def test_backfill_judgement_mode(self, tmp_path: Path) -> None:
        cfg = load_config(_bench_config(tmp_path, "mode.yaml", "  judgement_mode: answer\n"))
        tasks = _build_tasks(cfg)
        assert all(t.data.get("judgement_mode") == "answer" for t in tasks)

    def test_non_benchmark_path_keeps_config_value(self, tmp_path: Path) -> None:
        """非 benchmark 路径走 to_eval_task，不受回填逻辑影响（防回归）。"""
        p = tmp_path / "plain.yaml"
        p.write_text(
            """
experiment:
  name: plain
memory:
  name: m
task:
  memory_instruction: location
  sessions:
    - instruction: "s1"
    - instruction: "s2"
"""
        )
        cfg = load_config(p)
        assert cfg.to_eval_task().memory_instruction == "location"


class TestTestOnlyBenchmark:
    """test_only 协议 × benchmark：归一化后可构建（此前 validate 必挂）。"""

    def test_build_succeeds_and_forces_no_inject(self, tmp_path: Path) -> None:
        cfg = load_config(_bench_config(tmp_path, "testonly.yaml", "", protocol="test_only"))
        tasks = _build_tasks(cfg)
        assert tasks
        for task in tasks:
            assert task.sessions, "适配器产物应有 sessions"
            assert all(not s.memory_inject for s in task.sessions)

    def test_transfer_protocol_keeps_adapter_injects(self, tmp_path: Path) -> None:
        """对照组：transfer 协议下适配器的 memory_inject=True 保持原样。"""
        cfg = load_config(_bench_config(tmp_path, "transfer.yaml", ""))
        tasks = _build_tasks(cfg)
        assert all(any(s.memory_inject for s in t.sessions) for t in tasks)


class TestSmokeConfigsLoad:
    """默认 real smoke yaml 能 load + build（数据捆绑在仓库 data/smoke/，零下载）。"""

    def test_locomo_test_only_normalizes(self) -> None:
        cfg_path = Path(__file__).parent.parent / "configs" / "smoke" / "locomo_test_only.yaml"
        data = Path(__file__).parent.parent / "data" / "smoke" / "locomo_smoke.json"
        assert data.exists(), "捆绑 smoke 数据缺失（data/smoke/locomo_smoke.json）"
        cfg = load_config(cfg_path)
        tasks = _build_tasks(cfg)
        assert tasks
        assert all(not s.memory_inject for t in tasks for s in t.sessions)
        assert all(t.memory_instruction == "none" for t in tasks)

    def test_shopping_transfer_builds(self) -> None:
        """shopping smoke 配置能用捆绑数据构建出 >=2 session 的任务（协议要求）。"""
        cfg_path = Path(__file__).parent.parent / "configs" / "smoke" / "shopping_transfer.yaml"
        data = Path(__file__).parent.parent / "data" / "smoke" / "shopping_smoke.jsonl"
        assert data.exists(), "捆绑 shopping smoke 数据缺失"
        cfg = load_config(cfg_path)
        tasks = _build_tasks(cfg)
        assert tasks
        assert all(len(t.sessions) >= 2 for t in tasks)
