"""Scene capabilities shared by MemoryArena configuration, execution and scoring."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

SceneFamily = Literal["shopping", "travel", "search", "reasoning"]


class ArenaScene(BaseModel):
    """A scene selects an existing family without duplicating consumer name lists."""

    model_config = ConfigDict(frozen=True)

    family: SceneFamily
    official_name: str


ARENA_SCENES: dict[str, ArenaScene] = {
    "webshop": ArenaScene(family="shopping", official_name="webshop"),
    "travel_planner": ArenaScene(family="travel", official_name="travel_planner"),
    "browsecomp-plus": ArenaScene(family="search", official_name="browsecomp-plus"),
    "math": ArenaScene(family="reasoning", official_name="math"),
    "phys": ArenaScene(family="reasoning", official_name="phys"),
}


def arena_scene(name: str) -> ArenaScene:
    """Reject unsupported names consistently at the configuration boundary."""
    try:
        return ARENA_SCENES[name]
    except KeyError:
        raise ValueError(f"Unsupported MemoryArena scene: {name}") from None
