"""Bootstrap the unmodified official HTTP app with host-only tool endpoints.

Executed as a separate process; upstream imports never enter the evaluator.
"""

from __future__ import annotations

import importlib
import json
import socket
import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException

# Only load the sibling boundary; the worker need not install the framework.
from official_tools import OfficialTools
from pydantic import BaseModel, Field, JsonValue


class WorkerConfig(BaseModel):
    tools_config: dict[str, JsonValue]
    scene_families: dict[str, str]
    scene_factories: dict[str, str]


class ToolRequest(BaseModel):
    task_id: str
    tool: str = ""
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ShoppingTaskRequest(BaseModel):
    task_id: str
    row: dict[str, JsonValue]
    output_path: str
    step_index: int | None = Field(default=None, ge=0)


class ShoppingProductRequest(BaseModel):
    task_id: str
    asin: str


class ShoppingRewardRequest(BaseModel):
    task_id: str
    step_result: dict[str, JsonValue]
    ground_truth: dict[str, JsonValue]
    attribute_mode: Literal["auto", "llm", "string"] = "auto"
    attribute_model: str = "gpt-4o"


def configure_factory(factory: Callable[..., Any]) -> Callable[..., Any]:
    """Configure a newly constructed SDK client before publishing the environment."""

    def create(**config: Any) -> Any:
        environment = factory(**config)
        client = getattr(getattr(environment, "llm_backend", None), "client", None)
        if client is not None and hasattr(client, "max_retries"):
            client.max_retries = 0
        return environment

    return create


def main() -> None:
    reference = Path(sys.argv[1]).resolve()
    config = WorkerConfig.model_validate_json(sys.stdin.readline())
    control_output = sys.stdout
    sys.stdout = sys.stderr  # Upstream diagnostic prints cannot corrupt the readiness channel.
    sys.path.insert(0, str(reference))
    if len(sys.argv) > 2 and sys.argv[2] == "webshop":
        module = importlib.import_module("env.env_systems.web_shopping_env.runtime.service.launch_lite")
        serve(module.app, control_output)
        return
    official = importlib.import_module("env.env_server")
    for name, factory in list(official.ENV_FACTORIES.items()):
        official.ENV_FACTORIES[name] = configure_factory(factory)
    for name, original in config.scene_factories.items():
        if original not in official.ENV_FACTORIES:
            raise ValueError(f"Official environment factory unavailable: {original}")
        official.ENV_FACTORIES[name] = official.ENV_FACTORIES[original]
    catalog = OfficialTools(reference, config.tools_config, config.scene_families)
    app: FastAPI = official.app
    attribute_judges: dict[str, Any] = {}
    shopping_catalogs: dict[Path, Any] = {}

    def shopping_catalog(entry: dict[str, Any]) -> Any:
        catalog_dir = Path(entry["env"].product_catalog_dir).resolve()
        product_catalog = shopping_catalogs.get(catalog_dir)
        if product_catalog is None:
            helpers = importlib.import_module("env.env_systems.web_shopping_env.runtime.reward_helpers")
            product_catalog = helpers.load_catalog(catalog_dir)
            shopping_catalogs[catalog_dir] = product_catalog
        return product_catalog

    def tools(request: ToolRequest) -> dict[str, Any]:
        entry = official.ENVIRONMENTS.get(request.task_id)
        if entry is None:
            raise HTTPException(404, "Environment not initialized")
        return {"status": "ok", "task_id": request.task_id, "tools": catalog.prepare(entry["env_name"])}

    def tool(request: ToolRequest) -> dict[str, Any]:
        entry = official.ENVIRONMENTS.get(request.task_id)
        if entry is None:
            raise HTTPException(404, "Environment not initialized")
        result = catalog.call(entry["env_name"], entry["env"], request.tool, request.arguments)
        return {"status": "ok", "task_id": request.task_id, "result": result}

    def shopping_task(request: ShoppingTaskRequest) -> dict[str, Any]:
        module = importlib.import_module("env.env_systems.web_shopping_env.runtime.runner.task_files")
        task = module._reconstruct_task_def_from_hf_row(request.row)
        if request.step_index is not None:
            prefix, sections = module.split_agent_instruction(task["agent_instruction"])
            instruction = module.build_instruction_for_step(
                prefix, sections, request.step_index + 1, {}, include_history=False
            )
            task = module.build_single_step_task(task, request.step_index, instruction)
        Path(request.output_path).write_text(json.dumps(task), encoding="utf-8")
        return {"status": "ok", "task_id": request.task_id}

    def shopping_product(request: ShoppingProductRequest) -> dict[str, Any]:
        entry = official.ENVIRONMENTS.get(request.task_id)
        if entry is None or entry["env_name"] != "webshop":
            raise HTTPException(404, "WebShop environment not initialized")
        product_catalog = shopping_catalog(entry)
        return {
            "status": "ok",
            "task_id": request.task_id,
            "name": product_catalog.name_by_asin.get(request.asin.upper()),
        }

    def shopping_reward(request: ShoppingRewardRequest) -> dict[str, Any]:
        entry = official.ENVIRONMENTS.get(request.task_id)
        if entry is None or entry["env_name"] != "webshop":
            raise HTTPException(404, "WebShop environment not initialized")
        reward_module = importlib.import_module("env.env_systems.web_shopping_env.compute_reward")
        product_catalog = shopping_catalog(entry)
        mode = request.attribute_mode
        judge = None
        fallback_reason = None
        if mode in {"auto", "llm"}:
            judge = attribute_judges.get(request.attribute_model)
            if judge is None:
                try:
                    judge = reward_module.create_attribute_judge(
                        reference / ".env", request.attribute_model, 3, 1.5
                    )
                except Exception as exc:
                    # Upstream auto mode falls back to string reward whenever
                    # optional judge initialization fails, including SDK errors.
                    if mode == "llm":
                        raise
                    fallback_reason = type(exc).__name__
                else:
                    attribute_judges[request.attribute_model] = judge
            mode = "llm" if judge is not None else "string"
        reward = reward_module.compute_reward_for_step(
            request.step_result,
            request.ground_truth,
            product_catalog,
            attribute_judge=judge,
            judge_context={"task_id": request.task_id, "step": request.step_result.get("step")},
        )
        return {
            "status": "ok",
            "task_id": request.task_id,
            "attribute_mode": mode,
            "attribute_fallback_reason": fallback_reason,
            "reward": reward,
        }

    # Explicit registration preserves handler types when the optional FastAPI
    # package is absent from the host's strict-mypy environment.
    app.add_api_route("/env/tools", tools, methods=["POST"])
    app.add_api_route("/env/tool", tool, methods=["POST"])
    app.add_api_route("/env/shopping_task", shopping_task, methods=["POST"])
    app.add_api_route("/env/shopping_product", shopping_product, methods=["POST"])
    app.add_api_route("/env/shopping_reward", shopping_reward, methods=["POST"])
    serve(app, control_output, sdk_retry_policy="factory llm_backend SDK clients: max_retries=0")


def serve(app: FastAPI, control_output: Any, sdk_retry_policy: str | None = None) -> None:
    import uvicorn

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    packages = {}
    for package in (
        "anthropic",
        "openai",
        "datasets",
        "numpy",
        "pandas",
        "transformers",
        "faiss-cpu",
        "pydantic",
        "pyserini",
        "torch",
        "spacy",
        "en-core-web-lg",
        "fastmcp",
        "tevatron",
    ):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "not-installed"
    print(
        json.dumps(
            {
                "port": listener.getsockname()[1],
                "python": sys.version.split()[0],
                "fastapi": version("fastapi"),
                "uvicorn": version("uvicorn"),
                "packages": packages,
                "sdk_retry_policy": sdk_retry_policy,
            }
        ),
        file=control_output,
        flush=True,
    )
    server.run(sockets=[listener])


if __name__ == "__main__":
    main()
