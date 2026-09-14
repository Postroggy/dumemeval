"""模块依赖图纪律测试（AST 静态分析，不 import 被测模块）。

保证：
1. ``src/dumemeval/`` 内模块之间不存在循环依赖（含函数内延迟导入）。
2. 分层依赖方向不被打破：禁止高层反向依赖低层，关键禁令——
   ``execution`` 不依赖 ``adapters``；``verifier`` 只依赖 core/models（判分体系
   不复用 metrics）；``core`` 是最底层不依赖任何业务层；``cli`` 是顶层可依赖一切。

实现：用 ``ast`` 扫描每个模块的 import 语句（顶层 + 函数内），把相对导入
解析为绝对模块名，构造有向图后检测强连通分量（SCC）——SCC 规模 > 1 即循环。
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "dumemeval"
PKG = "dumemeval"

# 显式禁止边：key 层不允许依赖 value 集合里的层。
# 依据 CLAUDE.md「核心哲学：core ← 其余 ← cli」与分层禁区。
# 注意 pipeline 是编排层，允许访问 adapters/metrics 的接口（已实测为合法边）。
_FORBIDDEN_EDGES: dict[str, set[str]] = {
    "core": {
        "adapters",
        "execution",
        "verifier",
        "metrics",
        "datasets",
        "lifecycle",
        "pipeline",
        "comparison",
        "cli",
    },
    "execution": {"adapters"},  # CLAUDE.md：execution 不依赖 adapters
    "adapters": {"execution", "metrics", "datasets", "lifecycle", "pipeline", "comparison", "cli"},
    "verifier": {
        "metrics",
        "datasets",
        "adapters",
        "execution",
        "lifecycle",
        "pipeline",
        "comparison",
        "cli",
    },
    "metrics": {"datasets", "adapters", "execution", "lifecycle", "pipeline", "comparison", "cli"},
    "datasets": {"adapters", "execution", "lifecycle", "pipeline", "comparison", "cli"},
    "lifecycle": {"datasets", "pipeline", "comparison", "cli"},
    "pipeline": {"cli", "comparison"},
    "comparison": {"cli"},
    "cli": set(),  # 顶层，允许依赖一切
}
_LAYERS = tuple(_FORBIDDEN_EDGES)


def _module_name(path: Path) -> str:
    """src/dumemeval/a/b.py → dumemeval.a.b（__init__.py → dumemeval.a）。"""
    rel = path.relative_to(SRC)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join([PKG, *parts])


def _collect_imports(path: Path) -> list[str]:
    """收集一个模块的全部绝对依赖模块名（顶层 + 函数内 import 都算）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    me = _module_name(path)
    me_parts = me.split(".")
    # 相对导入的基准包：__init__.py 的 __package__ 就是自己，普通模块是上一级
    package = me_parts if path.name == "__init__.py" else me_parts[:-1]
    deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                deps.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:  # 绝对导入
                deps.add((node.module or "").split(".")[0])
            else:  # 相对导入：level=1 指当前包，level=2 指父包…
                base = package[: len(package) - node.level + 1]
                if node.module:
                    base = [*base, *node.module.split(".")]
                    deps.add(".".join(base))
                else:
                    # ``from . import X``：X 是同包下的模块/符号，解析为 X 而非包自身
                    # （指向包自身的边是假阳性，如 ``from . import prompts``）
                    for alias in node.names:
                        deps.add(".".join([*base, alias.name]))
    return sorted(deps)


def _build_graph() -> tuple[dict[str, set[str]], list[str]]:
    modules = [p for p in SRC.rglob("*.py") if p.name != "__init__.py" or p.parent != SRC]
    names = {_module_name(p): p for p in modules}
    graph: dict[str, set[str]] = {n: set() for n in names}
    for name, path in names.items():
        for dep in _collect_imports(path):
            # 只保留包内真实存在的模块边（from . import X 中 X 可能是符号而非模块）
            if dep.startswith(PKG) and dep != name and dep in names:
                graph[name].add(dep)
    return graph, sorted(names)


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[set[str]]:
    """Tarjan SCC：返回所有规模 > 1 的强连通分量。"""
    index_counter = 0
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: set[str] = set()
    result: list[set[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index_counter
        index[v] = index_counter
        lowlink[v] = index_counter
        index_counter += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, set()):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            comp: set[str] = set()
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.add(w)
                if w == v:
                    break
            if len(comp) > 1:
                result.append(comp)

    for v in graph:
        if v not in index:
            strongconnect(v)
    return result


def _layer_of(module: str) -> str | None:
    """模块所属层（取最长的已知层前缀，未分层模块返回 None）。"""
    parts = module.split(".")[1:]
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in _LAYERS:
            return prefix
    return None


def _assert_no_backward(graph: dict[str, set[str]]) -> list[str]:
    """分层方向：只允许依赖同层或更底层的模块（显式禁止边模型）。"""
    violations: list[str] = []
    for src_module, deps in graph.items():
        src_layer = _layer_of(src_module)
        if src_layer is None:
            continue
        forbidden = _FORBIDDEN_EDGES[src_layer]
        for dep in deps:
            dep_layer = _layer_of(dep)
            # core/models 是底层，任何人可依赖；其余按禁止边判断
            if dep_layer in forbidden:
                violations.append(f"{src_module} → {dep}（{src_layer} 禁止依赖 {dep_layer}）")
    return violations


def test_no_circular_imports() -> None:
    """模块图无循环依赖（AST 静态分析，含函数内延迟导入）。"""
    graph, _ = _build_graph()
    cycles = _strongly_connected_components(graph)
    assert cycles == [], f"存在循环依赖：{cycles}"


def test_no_layer_backward_dependency() -> None:
    """分层方向不被打破：禁止高层反向依赖低层。"""
    graph, _ = _build_graph()
    violations = _assert_no_backward(graph)
    assert not violations, "分层依赖方向违规：\n" + "\n".join(violations[:20])
