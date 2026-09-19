"""Thin loading of the official tool implementations inside the service process."""

from __future__ import annotations

import argparse
import importlib
import inspect
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import JsonValue


class OfficialTools:
    """Keep upstream dynamic APIs confined to this integration boundary."""

    def __init__(self, reference: Path, config: dict[str, JsonValue], scene_families: dict[str, str]) -> None:
        self.reference = reference
        self.config = config
        self.scene_families = scene_families
        self.travel: Any = None
        self.search: dict[str, Callable[..., Any]] = {}
        self.descriptions: list[dict[str, Any]] = []

    def tool(self, *, name: str, description: str) -> Callable[..., Any]:
        """Accept the registration API used by upstream register_tools unchanged."""

        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.search[name] = fn
            parameters = inspect.signature(fn).parameters
            self.descriptions.append(
                {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": {key: {"type": "string"} for key in parameters},
                        "required": list(parameters),
                    },
                }
            )
            return fn

        return register

    def prepare(self, scene: str) -> list[dict[str, Any]]:
        family = self.scene_families.get(scene)
        if family == "travel":
            module = importlib.import_module("env.env_systems.travel_planner_env.tool_executor")
            if self.travel is None:
                self.travel = module.ToolExecutor(
                    db_path=self.config.get("database")
                    or str(self.reference / "env/env_systems/travel_planner_env/database")
                )
            schemas = importlib.import_module("env.env_systems.travel_planner_env.tool_schemas").TOOLS
            return [item["function"] for item in schemas]
        if family == "search":
            if not self.search:
                self._prepare_search()
            return self.descriptions
        if family == "reasoning":
            return [
                {"name": "reasoning", "description": "Official reasoning tool; arguments: {task: string}."}
            ]
        if family != "shopping":
            raise ValueError(f"Unsupported official tool family for scene: {scene}")
        return [
            {
                "name": "action",
                "description": "WebShop action; arguments: {action: search[...] or click[...]}",
            }
        ]

    def _prepare_search(self) -> None:
        directory = self.reference / "env/env_systems/web_search_env/searcher"
        sys.path.insert(0, str(directory))
        searchers = importlib.import_module("searchers")
        searcher_class = searchers.SearcherType.get_searcher_class(self.config.get("searcher_type", "openai"))
        parser = argparse.ArgumentParser()
        searcher_class.parse_args(parser)
        supplied = self.config.get("searcher_args", {})
        if not isinstance(supplied, dict):
            raise ValueError("Search searcher_args must be an object")
        known = {action.dest: action for action in parser._actions}
        for name, value in supplied.items():
            if name not in known:
                raise ValueError(f"Unknown official search argument: {name}")
            known[name].default = value
            known[name].required = False
        args = parser.parse_args([])
        args.provider = self.config.get("provider", "openai")
        searcher = searcher_class(args)
        module = importlib.import_module("tools")
        module.register_tools(
            self, searcher, self.config.get("snippet_max_tokens", 512), self.config.get("k", 5), True
        )

    def call(self, scene: str, environment: Any, name: str, arguments: dict[str, JsonValue]) -> Any:
        catalog = self.prepare(scene)
        family = self.scene_families[scene]
        if family == "travel":
            allowed = {item["name"] for item in catalog}
            if name not in allowed:
                raise ValueError("Unknown travel tool")
            return self.travel.execute(name, arguments)
        if family == "search" and name in self.search:
            return self.search[name](**arguments)
        if family == "reasoning" and name == "reasoning":
            return environment.reasoning(str(arguments["task"]))
        raise ValueError("Unknown official tool")
