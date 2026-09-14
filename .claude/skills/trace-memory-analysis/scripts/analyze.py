#!/usr/bin/env python3
"""Trace Memory Analysis 引擎（参数化，可复算）。

子命令：
  profile  基础画像：规模/任务形态/工具/memory 调用/快照版本/时间节奏
  memory   深度分析：写入成功率/容量/冗余/写放大/演化链/触发/载体协同
  report   结论先行的报告骨架（读 stats.json 渲染 markdown）

用法：
  python3 analyze.py profile --sessions <trace_dir> --out <out_dir>
  python3 analyze.py memory  --sessions <trace_dir> --out <out_dir>
  python3 analyze.py report  --sessions <trace_dir> --out <out_dir> --name "报告名"

每个子命令把结果写入 <out>/stats.json（machine-readable，可复算）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# 快照块标题（Hermes 语义；其他系统可在 --mem-title 覆盖）
DEFAULT_MEM_TITLE = "MEMORY (your personal notes)"

TOOL_HINTS = {  # 用于"载体/通道"归类
    "memory": "memory",
    "skill_view": "skill-read",
    "skill_manage": "skill-write",
    "session_search": "session-search",
}


def pargs(raw) -> dict:
    try:
        v = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[，。；、,.;:：\"'()（）]", " ", str(s).lower())).strip()


def cmd_key(cmd: str) -> str:
    cmd = (cmd or "").strip()
    first = cmd.split()[0] if cmd.split() else "?"
    us = re.findall(r"https?://[^\s\"'\\<>]+", cmd)
    return f"{first} {sorted(us)[0][:90]}" if us else f"{first} {cmd[:60]}"


def tool_name(t) -> str:
    """兼容扁平（{"name": ...}）与嵌套（{"function": {"name": ...}}）两种 tools 格式。"""
    if isinstance(t, dict):
        n = t.get("name")
        if n:
            return str(n)
        fn = t.get("function")
        if isinstance(fn, dict):
            return str(fn.get("name") or "")
    return str(t)


def load_sessions(sessions_dir: Path, mem_title: str) -> list[dict]:
    files = sorted(p for p in sessions_dir.glob("*.json") if p.is_file())
    out = []
    for f in files:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        msgs = d.get("messages") or []
        tools = d.get("tools") or []
        # 三态：True=tools 字段存在且含 memory；False=有 tools 字段但不含；None=导出无 tools 字段
        has_mem_tool: bool | None = None
        if isinstance(d.get("tools"), list):
            has_mem_tool = "memory" in {tool_name(t) for t in tools}
        ops: list[dict] = []  # memory 调用
        tool_counter: Counter = Counter()
        last_user = -999
        for i, m in enumerate(msgs):
            if m.get("role") == "user" and not m.get("_empty_recovery_synthetic"):
                last_user = i
            for tc in m.get("tool_calls") or []:
                fn = tc["function"]["name"]
                tool_counter[fn] += 1
                if fn == "memory":
                    a = pargs(tc["function"].get("arguments"))
                    ops.append({
                        "i": i,
                        "act": a.get("action", "?"),
                        "c": str(a.get("content", "")),
                        "old": str(a.get("old_text", "")),
                        "dist": i - last_user,
                    })
        # 每个 memory 调用对应一个 tool 结果（assistant 后最近的 tool 消息）
        for op in ops:
            op["ok"] = None
            for j in range(op["i"] + 1, min(op["i"] + 4, len(msgs))):
                if msgs[j].get("role") == "tool":
                    content = str(msgs[j].get("content") or "")
                    op["ok"] = '"success": false' not in content
                    op["err"] = content[:200] if op["ok"] is False else ""
                    break
        sp = d.get("system_prompt", "")
        block, fill, entries = mem_block(sp, mem_title)
        try:
            dur = (datetime.fromisoformat(d["last_updated"]) - datetime.fromisoformat(d["session_start"])).total_seconds() / 60
        except Exception:
            dur = 0.0
        out.append({
            "id": f.stem,
            "day": d.get("session_start", "")[:10],
            "dur": round(dur, 1),
            "n_msgs": len(msgs),
            "n_user": sum(1 for m in msgs if m.get("role") == "user" and not m.get("_empty_recovery_synthetic")),
            "n_tools": sum(tool_counter.values()),
            "tools": dict(tool_counter),
            "mem_ops": ops,
            "n_mem_ok": sum(1 for op in ops if op["ok"]),
            "n_mem_fail": sum(1 for op in ops if op["ok"] is False),
            "mem_hash": hashlib.md5(block.encode()).hexdigest()[:8] if block else "-",
            "mem_fill": fill,
            "mem_entries": entries,
            "model": d.get("model"),
            "has_mem_tool": has_mem_tool,
        })
    return out


def mem_block(sp: str, mem_title: str) -> tuple[str, int, int]:
    i = sp.find(mem_title)
    if i < 0:
        return "", 0, 0
    m = re.search(r"\[(\d+)% — ([\d,]+)/([\d,]+) chars\]", sp)
    fill = int(m.group(1)) if m else 0
    st = sp.find("\n", sp.find("═", i))
    j = sp.find("═" * 10, st)
    block = sp[st + 1:j].strip() if j > 0 else ""
    return block, fill, len([e for e in block.split("\n§\n") if e.strip()])


# ── profile ────────────────────────────────────────────────────────────────

def profile(sessions: list[dict]) -> dict:
    n = len(sessions)
    tools = Counter()
    for s in sessions:
        tools.update(s["tools"])
    task_bins = Counter()
    for s in sessions:
        u = s["n_user"]
        task_bins["单轮(1)" if u == 1 else "多轮(2-5)" if u <= 5 else "长多轮(>5)"] += 1
    mem_ops = Counter()
    for s in sessions:
        for op in s["mem_ops"]:
            mem_ops[op["act"]] += 1
    day_cnt = Counter(s["day"] for s in sessions)
    mem_hashes = {}
    for s in sessions:
        h = s["mem_hash"]
        if h != "-":
            mem_hashes.setdefault(h, {"first": s["day"], "n": 0})["n"] += 1
    fills = [s["mem_fill"] for s in sessions if s["mem_fill"]]
    return {
        "n_sessions": n,
        "n_msgs": sum(s["n_msgs"] for s in sessions),
        "n_tools": sum(s["n_tools"] for s in sessions),
        "avg_tools_per_session": round(sum(s["n_tools"] for s in sessions) / max(n, 1), 1),
        "days": dict(sorted(day_cnt.items())),
        "models": dict(Counter(s["model"] for s in sessions)),
        "tools": tools.most_common(15),
        "task_shape": dict(task_bins.most_common()),
        "mem_ops": dict(mem_ops.most_common()),
        "mem_versions": len(mem_hashes),
        "mem_versions_detail": {h: v for h, v in sorted(mem_hashes.items(), key=lambda kv: kv[1]["first"])},
        "mem_fill_dist": {
            ">=90%": sum(1 for f in fills if f >= 90),
            ">=99%": sum(1 for f in fills if f >= 99),
            "100%": sum(1 for f in fills if f >= 100),
        },
        "n_mem_tool_in_place": sum(1 for s in sessions if s["has_mem_tool"] is True),
        "n_tools_field_missing": sum(1 for s in sessions if s["has_mem_tool"] is None),
        "n_with_mem_ops": sum(1 for s in sessions if s["mem_ops"]),
        "n_with_snapshot": sum(1 for s in sessions if s["mem_hash"] != "-"),
        "n_session_search": sum(1 for s in sessions if s["tools"].get("session_search", 0)),
    }


# ── memory 深度 ────────────────────────────────────────────────────────────

def deep(sessions: list[dict]) -> dict:
    ops = [op for s in sessions for op in s["mem_ops"]]
    n_ops = len(ops)
    n_ok = sum(1 for op in ops if op["ok"])
    n_fail = sum(1 for op in ops if op["ok"] is False)
    fail_by_action = Counter()
    fail_reason = Counter()
    for op in ops:
        if op["ok"] is False:
            fail_by_action[op["act"]] += 1
            low = (op.get("err") or "").lower()
            if "exceed the limit" in low or "would put memory" in low:
                fail_reason["超限/容量"] += 1
            elif "no entry matched" in low:
                fail_reason["找不到目标"] += 1
            elif "duplicate" in low or "already exists" in low:
                fail_reason["重复"] += 1
            elif "cannot be empty" in low:
                fail_reason["空内容"] += 1
            else:
                fail_reason["其他"] += 1

    # 重复写入（规范化去重）
    adds = [op["c"] for op in ops if op["act"] == "add" and op["c"].strip()]
    dup_adds = {k: v for k, v in Counter(norm(c) for c in adds).items() if v >= 2}

    # 写放大（replace 目标被改次数）
    reps = [op["old"] for op in ops if op["act"] == "replace" and op["old"].strip()]
    hot = {k: v for k, v in Counter(norm(o) for o in reps).items() if v >= 3}

    # 触发分布
    trig = Counter(
        "同块(≤2步)" if op["dist"] <= 2 else "3-5步" if op["dist"] <= 5 else "6-15步" if op["dist"] <= 15 else "自主(>15)"
        for op in ops
    )

    # 载体分布（memory / skill-read / skill-write / session-search / 其他）
    carrier = Counter()
    for s in sessions:
        for fn, cnt in s["tools"].items():
            carrier[TOOL_HINTS.get(fn, "其他")] += cnt

    return {
        "n_mem_calls": n_ops,
        "n_mem_success": n_ok,
        "n_mem_fail": n_fail,
        "mem_fail_rate": round(100 * n_fail / max(n_ops, 1), 1),
        "fail_by_action": dict(fail_by_action.most_common()),
        "fail_reason": dict(fail_reason.most_common()),
        "dup_writes": {k[:80]: v for k, v in sorted(dup_adds.items(), key=lambda kv: -kv[1])},
        "n_dup_knowledge": len(dup_adds),
        "hot_entries": {k[:80]: v for k, v in sorted(hot.items(), key=lambda kv: -kv[1])},
        "n_hot_entries": len(hot),
        "trigger_dist": dict(trig.most_common()),
        "carrier": dict(carrier.most_common()),
        "per_session_write_count": {
            "n_sessions_with_writes": sum(1 for s in sessions if s["mem_ops"]),
            "max_writes_in_session": max((len(s["mem_ops"]) for s in sessions), default=0),
        },
    }

# ── report 骨架 ────────────────────────────────────────────────────────────

def render_report(sessions: list[dict], out_dir: Path, name: str, mem_title: str) -> Path:
    p = profile(sessions)
    d = deep(sessions)
    md = f"""# {name} · Agent Trace Memory 分析

> 数据：{p['n_sessions']} 会话 · {p['n_msgs']} 消息 · {p['n_tools']} 工具调用 · 生成于 DuMemEval trace-memory-analysis

## 结论

> [!abstract] 结论
> （结论区待填：结论先行，分点，每条 结论→证据→含义。见 references/reporting.md）

## 一、数据概况

| 项 | 值 |
|---|---|
| 会话数 | {p['n_sessions']} |
| 消息总数 | {p['n_msgs']} |
| 工具调用 | {p['n_tools']}（人均 {p['avg_tools_per_session']}） |
| 模型 | {p['models']} |
| 任务形态 | {p['task_shape']} |
| memory 调用 | {p['mem_ops']}（成功 {d['n_mem_success']} / 失败 {d['n_mem_fail']}，失败率 {d['mem_fail_rate']}%） |
| memory 工具在位 | {p['n_mem_tool_in_place']}/{p['n_sessions']} 会话 |
| 快照注入 | {p['n_with_snapshot']}/{p['n_sessions']} 会话 · {p['mem_versions']} 个版本 |
| 填充率 | {p['mem_fill_dist']} |

## 二、关键数字（自动统计，供结论引用）

### 写入成功率
- 失败 {d['n_mem_fail']} 次，失败率 **{d['mem_fail_rate']}%**；按 action：{d['fail_by_action']}
- 失败原因：{d['fail_reason']}

### 容量
- 快照填充 ≥90%：{p['mem_fill_dist']['>=90%']} 会话 · ≥99%：{p['mem_fill_dist']['>=99%']} · 100% 满：{p['mem_fill_dist']['100%']}

### 冗余与写放大
- 重复写入知识 **{d['n_dup_knowledge']}** 条：{list(d['dup_writes'].items())[:5]}
- 热条目（被改 ≥3 次）**{d['n_hot_entries']}** 条：{list(d['hot_entries'].items())[:5]}

### 触发与载体
- 触发分布：{d['trigger_dist']}
- 载体分布：{d['carrier']}
- 写入会话：{d['per_session_write_count']}

## 三、核心发现

（结论 callout → 证据 → 含义，逐条填写；参考 references/reporting.md）

## 四、推理过程与结论边界

（至少一个例子说明结论怎么推的 + 局限）

## 五、值得关注的改进方向

（callout 分条，标注对应发现）

## 六、下一步计划

（立即可做 / 需配合）

---
*数字由 scripts/analyze.py 生成，可复算。*
"""
    out = out_dir / f"{name}-memory-analysis.md"
    out.write_text(md, encoding="utf-8")
    return out


# ── main ───────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(prog="trace-memory-analysis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("profile", "memory", "report"):
        p = sub.add_parser(c)
        p.add_argument("--sessions", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--name", default="trace")
        p.add_argument("--mem-title", default=DEFAULT_MEM_TITLE)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sessions = load_sessions(Path(args.sessions), args.mem_title)

    stats_path = out_dir / "stats.json"
    merged = {}
    if stats_path.exists():
        merged = json.loads(stats_path.read_text())
    if args.cmd in ("profile", "report"):
        merged["profile"] = profile(sessions)
    if args.cmd in ("memory", "report"):
        merged["memory"] = deep(sessions)
    stats_path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.cmd == "profile":
        p = merged["profile"]
        print(f"会话 {p['n_sessions']} | 消息 {p['n_msgs']} | 工具 {p['n_tools']} | "
              f"memory调用 {p['mem_ops']} | 版本 {p['mem_versions']} | 任务形态 {p['task_shape']}")
    elif args.cmd == "memory":
        m = merged["memory"]
        print(f"memory调用 {m['n_mem_calls']} | 失败率 {m['mem_fail_rate']}% | "
              f"失败原因 {m['fail_reason']} | 重复知识 {m['n_dup_knowledge']} | 热条目 {m['n_hot_entries']}")
    else:
        path = render_report(sessions, out_dir, args.name, args.mem_title)
        print(f"报告: {path}")
    print(f"stats: {stats_path}")


if __name__ == "__main__":
    sys.exit(main())
