"""The managed worker delegates Shopping reward and LLM attribute judging upstream."""

from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dumemeval.benchmarks.memoryarena.environment import config as arena_config


def test_worker_shopping_reward_calls_pinned_calculator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(Path(arena_config.__file__).parent))
    from dumemeval.benchmarks.memoryarena.environment import official as worker

    app = FastAPI()
    environment = SimpleNamespace(product_catalog_dir=str(tmp_path))
    server = SimpleNamespace(
        app=app,
        ENV_FACTORIES={"webshop": lambda **_kwargs: environment},
        ENVIRONMENTS={"task-1": {"env_name": "webshop", "env": environment}},
    )
    seen: list[tuple[str, Any]] = []

    def create_judge(env_path: Path, model: str, max_retries: int, retry_delay: float) -> object:
        seen.append(("judge", (env_path, model, max_retries, retry_delay)))
        if model == "broken-sdk":
            raise TypeError("Incompatible SDK")
        return object()

    def compute_reward(
        step_result: dict[str, Any],
        ground_truth: dict[str, Any],
        catalog: object,
        *,
        attribute_judge: object | None,
        judge_context: dict[str, Any],
    ) -> dict[str, Any]:
        seen.append(("reward", (step_result, ground_truth, catalog, attribute_judge, judge_context)))
        return {"reward": 0.75, "components": {"attr_match_ratio": 0.5}}

    reward_module = SimpleNamespace(
        create_attribute_judge=create_judge, compute_reward_for_step=compute_reward
    )
    catalog = SimpleNamespace(name_by_asin={"PURCHASED": "Product"})
    catalog_loads: list[Path] = []

    def load_catalog(path: Path) -> object:
        catalog_loads.append(path)
        return catalog

    helpers = SimpleNamespace(load_catalog=load_catalog)
    original_import = importlib.import_module

    def import_official(name: str) -> Any:
        if name == "env.env_server":
            return server
        if name == "env.env_systems.web_shopping_env.compute_reward":
            return reward_module
        if name == "env.env_systems.web_shopping_env.runtime.reward_helpers":
            return helpers
        return original_import(name)

    monkeypatch.setattr(importlib, "import_module", import_official)
    monkeypatch.setattr(worker, "OfficialTools", lambda *_args: object())
    monkeypatch.setattr(worker, "serve", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["official.py", str(tmp_path), "environment"])
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tools_config": {},
                    "scene_families": {},
                    "scene_factories": {"webshop": "webshop"},
                }
            )
            + "\n"
        ),
    )
    original_stdout = sys.stdout
    try:
        worker.main()
    finally:
        sys.stdout = original_stdout

    with TestClient(app) as client:
        response = client.post(
            "/env/shopping_reward",
            json={
                "task_id": "task-1",
                "step_result": {"step": 1, "purchased_asin": "PURCHASED"},
                "ground_truth": {"target_asin": "TARGET"},
                "attribute_mode": "llm",
                "attribute_model": "judge-model",
            },
        )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "task_id": "task-1",
        "attribute_mode": "llm",
        "attribute_fallback_reason": None,
        "reward": {"reward": 0.75, "components": {"attr_match_ratio": 0.5}},
    }
    assert seen[0] == ("judge", (tmp_path / ".env", "judge-model", 3, 1.5))
    step, ground_truth, used_catalog, judge, context = seen[1][1]
    assert step == {"step": 1, "purchased_asin": "PURCHASED"}
    assert ground_truth == {"target_asin": "TARGET"}
    assert used_catalog is catalog and judge is not None
    assert context == {"task_id": "task-1", "step": 1}
    with TestClient(app) as client:
        auto = client.post(
            "/env/shopping_reward",
            json={
                "task_id": "task-1",
                "step_result": {"step": 2, "purchased_asin": "PURCHASED"},
                "ground_truth": {"target_asin": "TARGET"},
                "attribute_mode": "auto",
                "attribute_model": "broken-sdk",
            },
        )
        product = client.post("/env/shopping_product", json={"task_id": "task-1", "asin": "PURCHASED"})
    assert auto.status_code == 200
    assert auto.json()["attribute_mode"] == "string"
    assert auto.json()["attribute_fallback_reason"] == "TypeError"
    assert seen[-1][1][3] is None
    assert product.json()["name"] == "Product"
    assert catalog_loads == [tmp_path.resolve()]
