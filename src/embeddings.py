"""Embedding providers.

Documents and queries use different Gemini task types, which improves retrieval
for asymmetric search. Vectors are L2-normalized because Gemini recommends
re-normalizing when ``output_dimensionality`` is below the model default.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol, Sequence, runtime_checkable

from .llm import LLMError, retry_with_backoff

LOGGER = logging.getLogger(__name__)


@runtime_checkable
class Embedder(Protocol):
    dimensions: int
    model: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0:
        return list(vector)
    return [value / norm for value in vector]


class GeminiEmbedder:
    """Batch embedding client for ``gemini-embedding-001`` (or compatible)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-001",
        dimensions: int = 768,
        batch_size: int = 32,
        max_retries: int = 4,
        base_delay_s: float = 1.5,
        inputs_per_minute: int = 90,
    ) -> None:
        if not api_key:
            raise LLMError("A Gemini API key is required for embeddings")
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, batch_size)
        self.max_retries = max_retries
        self.base_delay_s = base_delay_s
        # The free tier counts each embedded text against a per-minute budget.
        self.inputs_per_minute = max(0, inputs_per_minute)

    def _embed(self, texts: Sequence[str], task_type: str) -> list[list[float]]:
        from google.genai import types

        def _call(batch: list[str]) -> list[list[float]]:
            response = self._client.models.embed_content(
                model=self.model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self.dimensions,
                ),
            )
            embeddings = list(response.embeddings or [])
            if len(embeddings) != len(batch):
                raise LLMError(
                    f"Embedding count mismatch: expected {len(batch)}, got {len(embeddings)}"
                )
            return [_normalize(item.values or []) for item in embeddings]

        vectors: list[list[float]] = []
        window_started = time.monotonic()
        window_inputs = 0
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            if self.inputs_per_minute:
                if window_inputs + len(batch) > self.inputs_per_minute:
                    wait = 60.0 - (time.monotonic() - window_started)
                    if wait > 0:
                        LOGGER.info("Embedding quota window full; waiting %.0fs", wait)
                        time.sleep(wait)
                    window_started = time.monotonic()
                    window_inputs = 0
                window_inputs += len(batch)
            vectors.extend(
                retry_with_backoff(
                    lambda batch=batch: _call(batch),
                    max_retries=self.max_retries,
                    base_delay_s=self.base_delay_s,
                    label=f"embed_content[{task_type}]",
                )
            )
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(texts, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], task_type="RETRIEVAL_QUERY")[0]
