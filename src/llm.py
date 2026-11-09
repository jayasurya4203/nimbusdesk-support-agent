"""Gemini LLM client with structured JSON output and retry handling.

The agent depends on the small :class:`LLMClient` protocol rather than the
Gemini SDK directly, which keeps the workflow testable with fake clients.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any, Protocol, runtime_checkable

LOGGER = logging.getLogger(__name__)

_RETRYABLE_MARKERS = (
    "429",
    "RESOURCE_EXHAUSTED",
    "500",
    "INTERNAL",
    "502",
    "503",
    "UNAVAILABLE",
    "504",
    "DEADLINE_EXCEEDED",
    "timed out",
    "timeout",
    "connection reset",
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class LLMError(RuntimeError):
    """Raised when the model call fails after retries or returns invalid data."""


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int) and code in {429, 500, 502, 503, 504}:
        return True
    text = f"{type(exc).__name__}: {exc}".upper()
    return any(marker.upper() in text for marker in _RETRYABLE_MARKERS)


def retry_with_backoff(
    func,
    *,
    max_retries: int = 4,
    base_delay_s: float = 1.5,
    label: str = "model call",
):
    """Call ``func`` and retry transient failures with exponential backoff + jitter."""
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - classified below
            last_error = exc
            if attempt >= max_retries - 1 or not _is_retryable(exc):
                break
            delay = base_delay_s * (2**attempt) + random.uniform(0, 0.5)
            LOGGER.warning(
                "%s failed (attempt %d/%d): %s. Retrying in %.1fs",
                label,
                attempt + 1,
                max_retries,
                exc,
                delay,
            )
            time.sleep(delay)
    raise LLMError(f"{label} failed after {max_retries} attempt(s): {last_error}") from last_error


def parse_json_response(text: str | None) -> dict[str, Any]:
    """Parse a model JSON response, tolerating markdown code fences."""
    if not text or not text.strip():
        raise LLMError("Model returned an empty response")
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError(f"Expected a JSON object, got {type(data).__name__}")
    return data


@runtime_checkable
class LLMClient(Protocol):
    """Minimal interface used by the classifier, generator, and handoff builder."""

    def generate_json(
        self,
        *,
        prompt: str,
        system_instruction: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
    ) -> dict[str, Any]: ...

    def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str,
        temperature: float = 0.2,
    ) -> str: ...


class GeminiLLM:
    """Thin wrapper around ``google-genai`` with JSON schema enforcement."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        max_retries: int = 4,
        base_delay_s: float = 1.5,
    ) -> None:
        if not api_key:
            raise LLMError("A Gemini API key is required")
        from google import genai  # imported lazily so tests do not need the SDK

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.max_retries = max_retries
        self.base_delay_s = base_delay_s

    def _config(
        self,
        *,
        system_instruction: str,
        temperature: float,
        schema: dict[str, Any] | None = None,
        json_mode: bool = False,
    ):
        from google.genai import types

        kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_mime_type"] = "application/json"
        if schema is not None:
            kwargs["response_schema"] = schema
        return types.GenerateContentConfig(**kwargs)

    def generate_json(
        self,
        *,
        prompt: str,
        system_instruction: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._config(
                    system_instruction=system_instruction,
                    temperature=temperature,
                    schema=schema,
                    json_mode=True,
                ),
            )
            return parse_json_response(response.text)

        return retry_with_backoff(
            _call,
            max_retries=self.max_retries,
            base_delay_s=self.base_delay_s,
            label=f"generate_json[{self.model}]",
        )

    def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str,
        temperature: float = 0.2,
    ) -> str:
        def _call() -> str:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._config(
                    system_instruction=system_instruction,
                    temperature=temperature,
                ),
            )
            text = (response.text or "").strip()
            if not text:
                raise LLMError("Model returned an empty response")
            return text

        return retry_with_backoff(
            _call,
            max_retries=self.max_retries,
            base_delay_s=self.base_delay_s,
            label=f"generate_text[{self.model}]",
        )
