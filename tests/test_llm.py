"""Retry backoff and embedding quota pacing tests."""

from __future__ import annotations

import pytest

from src import embeddings, llm


class _FakeAPIError(Exception):
    def __init__(self, retry_delay: str | None = None) -> None:
        details = {"error": {"code": 429, "details": []}}
        if retry_delay:
            details["error"]["details"].append(
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}
            )
        self.details = details
        super().__init__("429 RESOURCE_EXHAUSTED")


def test_server_retry_delay_reads_retry_info() -> None:
    assert llm._server_retry_delay(_FakeAPIError("35s")) == 35.0
    assert llm._server_retry_delay(_FakeAPIError("1.5s")) == 1.5
    assert llm._server_retry_delay(_FakeAPIError()) == 0.0
    assert llm._server_retry_delay(RuntimeError("no details")) == 0.0


def test_backoff_waits_for_the_server_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", slept.append)
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise _FakeAPIError("42s")
        return "ok"

    assert llm.retry_with_backoff(flaky, max_retries=2, base_delay_s=0.0) == "ok"
    assert attempts["count"] == 2
    assert slept and slept[0] >= 43.0


def test_embedder_paces_inputs_under_the_minute_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    clock = {"now": 0.0}

    monkeypatch.setattr(embeddings.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(embeddings.time, "sleep", sleeps.append)

    embedder = embeddings.GeminiEmbedder.__new__(embeddings.GeminiEmbedder)
    embedder.model = "fake"
    embedder.dimensions = 4
    embedder.batch_size = 3
    embedder.max_retries = 1
    embedder.base_delay_s = 0.0
    embedder.inputs_per_minute = 5

    calls: list[list[str]] = []

    class _Client:
        class models:
            @staticmethod
            def embed_content(*, model, contents, config):
                calls.append(list(contents))
                clock["now"] += 1.0
                return type(
                    "Response",
                    (),
                    {"embeddings": [type("E", (), {"values": [1.0, 0.0, 0.0, 0.0]})() for _ in contents]},
                )()

    embedder._client = _Client()

    vectors = embedder.embed_documents([f"text {index}" for index in range(8)])

    assert len(vectors) == 8
    assert [len(call) for call in calls] == [3, 3, 2]
    assert sleeps and sleeps[0] == pytest.approx(59.0)
