"""HTTP contract tests only; the fake transport is not an official environment run."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
import requests

from dumemeval.benchmarks.memoryarena.environment.client import ArenaClient
from dumemeval.benchmarks.memoryarena.environment.config import ArenaConnection


def response(payload: dict[str, object], status: int = 200) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    return result


def ok(client: ArenaClient, **kwargs: object) -> requests.Response:
    return response({"status": "ok", "task_id": client.task_id, **kwargs})


def test_readiness_initialize_reset_step_close_in_order() -> None:
    with patch("requests.Session") as factory:
        client = ArenaClient(ArenaConnection(base_url="http://localhost:8001/", env_name="webshop"))
        http = factory.return_value
        http.request.side_effect = [
            ok(client, available_environments=["webshop"]),
            ok(client),
            ok(client, observation={"state": "ready"}),
            ok(
                client,
                observation={"state": "bought"},
                info={"purchased_asins": ["B000000001"]},
                reward=False,
                done=True,
            ),
            ok(client),
        ]
        with client:
            assert client.reset(seed=37).observation["state"] == "ready"
            evidence = client.step("click[Buy Now]")
            assert evidence.reward == 0
            assert evidence.info["purchased_asins"] == ["B000000001"]
        client.close()
        assert http.request.call_count == 5
        assert http.request.call_args_list[2].kwargs["json"]["seed"] == 37
        assert [event.operation for event in client.events] == [
            "available",
            "initialize",
            "reset",
            "step",
            "close",
        ]
        assert all(call.kwargs["timeout"] == 30 for call in http.request.call_args_list)
        assert all(call.kwargs["allow_redirects"] is False for call in http.request.call_args_list)


def test_timeout_never_replays_mutation_and_allows_reconciliation() -> None:
    with patch("requests.Session") as factory:
        client = ArenaClient(ArenaConnection(base_url="http://localhost:8001", env_name="webshop"))
        http = factory.return_value
        http.request.side_effect = [
            ok(client, available_environments=["webshop"]),
            ok(client),
            requests.Timeout("SECRET from transport"),
            ok(client, observation={"purchases": []}),
            ok(client),
        ]
        with client:
            with pytest.raises(RuntimeError, match="ambiguous") as failure:
                client.step("click[Buy Now]")
            assert "SECRET" not in str(failure.value)
            with pytest.raises(RuntimeError, match="ambiguous"):
                client.step("click[Buy Now]")
            assert client.observation().observation == {"purchases": []}
        assert [event.operation for event in client.events].count("step") == 1
        assert client.events[2].status == "ambiguous"


def test_unavailable_factory_fails_without_initializing() -> None:
    with patch("requests.Session") as factory:
        client = ArenaClient(ArenaConnection(base_url="http://localhost:8001", env_name="math"))
        factory.return_value.request.return_value = ok(client, available_environments=["webshop"])
        with pytest.raises(RuntimeError, match="factory unavailable"), client:
            pytest.fail("must not reach body")
        assert factory.return_value.request.call_count == 1


def test_cleanup_runs_on_agent_failure_and_does_not_mask_it() -> None:
    with patch("requests.Session") as factory:
        client = ArenaClient(ArenaConnection(base_url="http://localhost:8001", env_name="phys"))
        factory.return_value.request.side_effect = [
            ok(client, available_environments=["phys"]),
            ok(client),
            ok(client, warning="cleanup failed"),
        ]
        with pytest.raises(ValueError, match="agent failure") as failure, client:
            raise ValueError("agent failure")
        assert "cleanup warning" in failure.value.__notes__[0]
        assert client.events[-1].operation == "close"
        assert client.events[-1].status == "failed"


def test_initialization_timeout_still_attempts_owned_cleanup() -> None:
    with patch("requests.Session") as factory:
        client = ArenaClient(ArenaConnection(base_url="http://localhost:8001", env_name="math"))
        factory.return_value.request.side_effect = [
            ok(client, available_environments=["math"]),
            requests.Timeout(),
            ok(client),
        ]
        with pytest.raises(RuntimeError, match="initialize ambiguous"), client:
            pytest.fail("must not reach body")
        assert [event.operation for event in client.events] == ["available", "initialize", "close"]


def test_two_clients_never_share_environment_identity() -> None:
    with patch("requests.Session", return_value=Mock()):
        config = ArenaConnection(base_url="http://localhost:8001", env_name="travel_planner")
        assert ArenaClient(config).task_id != ArenaClient(config).task_id


@pytest.mark.parametrize(
    "malformed", [{"observation": "not-an-object"}, {"observation": {}, "task_id": "another-task"}, {}]
)
def test_malformed_action_response_is_ambiguous_and_not_replayed(malformed: dict[str, object]) -> None:
    with patch("requests.Session") as factory:
        client = ArenaClient(ArenaConnection(base_url="http://localhost:8001", env_name="math"))
        factory.return_value.request.side_effect = [
            ok(client, available_environments=["math"]),
            ok(client),
            ok(client, **malformed),
            ok(client),
        ]
        with client:
            with pytest.raises(RuntimeError, match="ambiguous"):
                client.step("candidate")
            with pytest.raises(RuntimeError, match="ambiguous"):
                client.step("candidate")
        assert [event.operation for event in client.events].count("step") == 1


@pytest.mark.parametrize(
    "url", ["file:///tmp/server", "http://user:secret@localhost", "http://localhost?key=secret"]
)
def test_secret_bearing_or_non_http_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        ArenaConnection(base_url=url, env_name="math")
