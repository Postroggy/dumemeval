"""MemoryCD 数据集适配（跨域长期个性化）。

数据：Dataset/data/MemoryCD/users/cross_domain_users_sampled.jsonl.gz
组织：每个用户 → 一个 EvalTask：
  - session 1：注入跨域记忆（其他域交互文本）
  - session 2..N：目标域预测任务（rating/summarization/ranking）
指标：MAE/RMSE（rating）、ROUGE-L（summarization）、NDCG@5/Recall@5（ranking）

Source: https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023 （MemoryCD 上游语料）
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...models import EvalTask, SessionSpec
from ..benchmark import BenchmarkAdapter, BenchmarkData, register_benchmark

_DOMAINS = ("Beauty_and_Personal_Care", "Books", "Electronics", "Home_and_Kitchen")


class MemoryCDTask(BaseModel):
    query: str = ""
    task_type: str = "rating"  # rating / summarization / generation / ranking
    target: Any = None
    item_asin: str = ""


class MemoryCDUser(BaseModel):
    user_id: str = ""
    interactions: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class MemoryCDData(BenchmarkData):
    users: list[MemoryCDUser] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> MemoryCDData:
        users: list[MemoryCDUser] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            users.append(
                MemoryCDUser(
                    user_id=str(item.get("user_id", "")),
                    interactions={
                        str(domain): list(items or [])
                        for domain, items in (item.get("interactions") or {}).items()
                    },
                )
            )
        return cls(users=users)

    @staticmethod
    def load_gz(path: str | Path, limit: int = 0) -> MemoryCDData:
        """加载 gzip jsonl（官方数据），limit=0 加载全部。"""
        rows: list[dict[str, Any]] = []
        with gzip.open(path, "rt") as f:
            for i, line in enumerate(f):
                if not line.strip():
                    continue
                rows.append(json.loads(line))
                if limit and i + 1 >= limit:
                    break
        return MemoryCDData.from_raw(rows)


@register_benchmark
class MemoryCDAdapter(BenchmarkAdapter):
    name = "memorycd"

    @property
    def data_type(self) -> type[BenchmarkData]:
        return MemoryCDData

    def build_tasks(self, data: BenchmarkData) -> list[EvalTask]:
        if not isinstance(data, MemoryCDData):
            raise TypeError(f"Expected MemoryCDData, got {type(data)}")
        tasks: list[EvalTask] = []
        for user in data.users:
            if not user.interactions:
                continue
            # 跨域：memory = 目标域之外的交互；target = 目标域测试交互
            # 简化：每个用户取第一个域做目标，其余域做记忆
            domains = list(user.interactions.keys())
            if len(domains) < 2:
                continue
            target_domain = domains[0]
            memory_domains = [d for d in domains if d != target_domain]
            memory_text = "\n".join(
                f"[{domain}] {inter.get('title', '')} rating={inter.get('rating', '')}: {inter.get('text', '')[:200]}"
                for domain in memory_domains
                for inter in (user.interactions.get(domain) or [])[:20]
            )
            target_items = (user.interactions.get(target_domain) or [])[:10]
            tasks_list: list[MemoryCDTask] = []
            sessions = [
                SessionSpec(
                    id=1,
                    instruction=f"以下是用户在其他领域的购买/评价历史，请记住其偏好：\n\n{memory_text}",
                    memory_inject=True,
                )
            ]
            for i, item in enumerate(target_items, start=2):
                query = f"请预测用户对商品 {item.get('title', item.get('asin', ''))} 的评分（1-5）。"
                sessions.append(SessionSpec(id=i, instruction=query, memory_inject=True, query=query))
                tasks_list.append(
                    MemoryCDTask(
                        query=query,
                        task_type="rating",
                        target=item.get("rating", 0.0),
                        item_asin=str(item.get("asin", "")),
                    )
                )
            if not tasks_list:
                continue
            tasks.append(
                EvalTask(
                    name=f"memorycd_{user.user_id[:8]}",
                    description=f"MemoryCD {user.user_id[:8]}（{len(tasks_list)} 题）",
                    sessions=sessions,
                    data={"tasks": [t.model_dump() for t in tasks_list]},
                    benchmark="memorycd",
                )
            )
        return tasks
