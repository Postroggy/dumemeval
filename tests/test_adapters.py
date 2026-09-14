"""测试：Memory 适配器层。"""

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dumemeval.adapters.directory import CONTAINER_MEMORY_DIR, DirectoryMemoryAdapter
from dumemeval.adapters.registry import create_adapter
from dumemeval.models import EvalTask, MemorySpec, SessionSpec


@pytest.fixture
def mem_spec(tmp_path: Path) -> MemorySpec:
    return MemorySpec(name="test-mem", type="directory", path=str(tmp_path / "memory"))


@pytest.fixture
def task() -> EvalTask:
    return EvalTask(
        name="test-task",
        sessions=[
            SessionSpec(id=1, instruction="记住偏好", memory_inject=True),
            SessionSpec(id=2, instruction="应用偏好", memory_inject=True),
        ],
    )


def test_directory_adapter_lifecycle(mem_spec: MemorySpec, task: EvalTask, tmp_path: Path) -> None:
    """验证目录型 adapter 完整生命周期：setup → inject → snapshot → observe。"""
    adapter = DirectoryMemoryAdapter(mem_spec)
    adapter.setup(task)
    assert adapter.memory_dir.exists()

    # setup 后目录为空（clear 语义）
    assert list(adapter.memory_dir.iterdir()) == []

    # inject：声明挂载（旧实现依赖 agent_memory_target，但无执行器设置该键，
    # 注入永远静默跳过；现走统一 memory_mounts 契约，详见
    # docs/adapters/memory-injection-contract.md）
    ctx: dict[str, Any] = {"agent_env": {}}
    adapter.inject(task.sessions[0], ctx)
    mounts = ctx["memory_mounts"]
    assert [m.container_path for m in mounts] == [CONTAINER_MEMORY_DIR]

    # snapshot
    snap = adapter.snapshot(task.sessions[0], tmp_path / "snapshots")
    assert snap.exists()

    # observe（session 级 ops：inject + snapshot）
    ops = adapter.observe(task.sessions[0])
    assert any(op.op == "inject" for op in ops)
    assert any(op.op == "snapshot" for op in ops)

    # 全局 ops 包含 setup
    all_ops = adapter.all_ops()
    assert any(op.op == "setup" for op in all_ops)


def test_directory_adapter_read_memory_files(mem_spec: MemorySpec, task: EvalTask) -> None:
    """验证 read_memory_files 读取目录内容。"""
    adapter = DirectoryMemoryAdapter(mem_spec)
    adapter.setup(task)
    (adapter.memory_dir / "pref.md").write_text("Alice likes latte")
    files = adapter.read_memory_files()
    assert files == {"pref.md": "Alice likes latte"}


def test_directory_adapter_reads_without_setup(mem_spec: MemorySpec, tmp_path: Path) -> None:
    """resume 跳过 setup 时仍能读已有 memory 目录（构造时绑定 path）。"""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "pref.md").write_text("Alice likes latte")
    adapter = DirectoryMemoryAdapter(mem_spec)
    assert adapter.read_memory_files() == {"pref.md": "Alice likes latte"}


def test_registry_create_unknown_type() -> None:
    """未知 adapter 类型由 registry 报错（配置不再用 Literal 锁死内置名单）。"""
    with pytest.raises(ValueError, match="Unknown memory adapter type"):
        create_adapter(MemorySpec(name="x", type="bogus"))


def test_register_adapter_is_the_extension_point() -> None:
    """社区加 backend：register_adapter 装饰器注册后 create_adapter 即可创建。"""
    from dumemeval.adapters import registry as _reg

    class ToyMemoryAdapter(DirectoryMemoryAdapter):
        type_name = "toy_mem"

    _reg.register_adapter(ToyMemoryAdapter)
    try:
        adapter = create_adapter(MemorySpec(name="t", type="toy_mem"))
        assert isinstance(adapter, ToyMemoryAdapter)
        assert adapter.name == "t"
    finally:
        _reg._ADAPTER_REGISTRY.pop("toy_mem", None)


def test_http_adapter_requires_base_url() -> None:
    """HTTP adapter 缺 base_url 应报错。"""
    from dumemeval.adapters.http import HttpMemoryAdapter

    with pytest.raises(ValueError, match="requires base_url"):
        HttpMemoryAdapter(MemorySpec(name="x", type="http")).setup(EvalTask(name="t"))


def test_http_adapter_retries_transient_post(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP _post 遇到瞬时 500 会重试后成功。"""
    from dumemeval.adapters.http import HttpMemoryAdapter

    adapter = HttpMemoryAdapter(MemorySpec(name="x", type="http", base_url="http://memory.local"))
    adapter.base_url = "http://memory.local"
    adapter.user_id = "u"
    calls = {"n": 0}

    class _Resp:
        def raise_for_status(self) -> None:
            if calls["n"] < 2:
                err = RuntimeError("500 Internal Server Error")
                err.response = type("R", (), {"status_code": 500})()  # type: ignore[attr-defined]
                raise err

        def json(self) -> dict[str, str]:
            return {"ok": "1"}

    class _Session:
        def post(self, url: str, json: dict[str, object], timeout: int) -> _Resp:
            calls["n"] += 1
            return _Resp()

    adapter.session = _Session()  # type: ignore[assignment]
    monkeypatch.setattr("dumemeval.core.retry.time.sleep", lambda _s: None)
    body = adapter._post("/memory/add", {"chunk": "x"})
    assert body == {"ok": "1"}
    assert calls["n"] == 2
