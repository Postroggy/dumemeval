"""Runtime ownership of the environment worker and its optional HTTP backend."""

from pathlib import Path

from pydantic import JsonValue

from dumemeval.models.memoryarena import arena_scene

from .config import ArenaRuntimeConfig
from .service import OfficialService


class WebShopBackend(OfficialService):
    """Serve product search/pages; the environment worker owns purchase episodes."""

    def __init__(self, config: ArenaRuntimeConfig, directory: Path) -> None:
        super().__init__(config, directory, mode="webshop")

    def environment_config(self) -> dict[str, JsonValue]:
        return {"bootstrap_upstream_env": False, "upstream_env_server_base": self.url}


class ArenaServices:
    """Start, reap and fingerprint all processes even after partial startup."""

    def __init__(self, config: ArenaRuntimeConfig, directory: Path) -> None:
        self.environment = OfficialService(config, directory)
        self.backend = (
            WebShopBackend(config, directory / "webshop")
            if arena_scene(config.env_name).family == "shopping"
            else None
        )
        self._closed = False

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("Official services cannot be restarted")
        try:
            self.environment.start()
            if self.backend is not None:
                self.backend.start()
        except Exception as error:
            try:
                self.close()
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    "Official service startup and cleanup failed", [error, cleanup_error]
                ) from error
            raise

    def environment_config(self) -> dict[str, JsonValue]:
        return self.backend.environment_config() if self.backend is not None else {}

    def provenance(self) -> dict[str, JsonValue]:
        if self.backend is None:
            return {}
        return {"webshop": {**self.backend.fingerprint, "url": self.backend.url}}

    def controls(self) -> dict[str, JsonValue]:
        if self.backend is None:
            return {}
        return {"webshop": self.backend.stable_fingerprint()}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[Exception] = []
        for service in (self.backend, self.environment):
            if service is not None:
                try:
                    service.close()
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise ExceptionGroup("Official service cleanup failed", errors)
