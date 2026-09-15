"""Protocol-shaped responses must preserve judge answers through the real SDK."""

from typing import Any

import httpx
import pytest

from dumemeval.verifier.clients import OpenAIJudgeClient


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            [
                {"type": "output_text", "text": "COR", "annotations": []},
                {"type": "output_text", "text": "RECT", "annotations": []},
            ],
            "CORRECT",
        ),
        ([{"type": "refusal", "refusal": "Unable to judge this input."}], ""),
    ],
)
def test_responses_judge_extracts_only_answer_content(
    monkeypatch: pytest.MonkeyPatch, content: list[dict[str, Any]], expected: str
) -> None:
    openai = pytest.importorskip("openai")
    paths: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "gpt-5.5",
                "output": [
                    {
                        "id": "rs_fixture",
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "Not the judge verdict."}],
                    },
                    {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": content,
                    },
                ],
            },
        )

    with openai.OpenAI(
        api_key="fixture-key",
        base_url="https://judge.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        max_retries=0,
    ) as sdk:
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: sdk)
        client = OpenAIJudgeClient("fixture-key", "https://judge.invalid/v1")
        assert client.complete("gpt-5.5", "Judge the answer.", "An answer.", 0, 128) == expected

    assert paths == ["/v1/responses"]
