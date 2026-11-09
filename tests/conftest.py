"""Shared test fixtures: deterministic fake embedder, scripted LLM, corpus."""

from __future__ import annotations

import copy
import hashlib
import math
import re
from pathlib import Path
from typing import Any, Sequence

import pytest

from src.agent import SupportAgent
from src.config import Settings
from src.escalator import EscalationConfig, EscalationPolicy, SensitiveTopicDetector
from src.generator import GENERATION_SCHEMA, ResponseGenerator
from src.handoff import HANDOFF_SCHEMA, HandoffBuilder
from src.models import RetrievedChunk
from src.persona import PERSONA_SCHEMA, PersonaClassifier

DIM = 48
EMBEDDING_MODEL = "fake-embedding"


def _vector(text: str, dimensions: int = DIM) -> list[float]:
    values = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        if len(token) < 2:
            continue
        digest = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16)
        sign = 1.0 if (digest >> 7) & 1 else -1.0
        values[digest % dimensions] += sign
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values] if norm else values


class FakeEmbedder:
    model = EMBEDDING_MODEL
    dimensions = DIM

    def __init__(self, model: str = EMBEDDING_MODEL, dimensions: int = DIM) -> None:
        self.model = model
        self.dimensions = dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [_vector(text, self.dimensions) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return _vector(text, self.dimensions)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = dict(
        gemini_api_key="test-key",
        chat_model="fake-chat",
        embedding_model=EMBEDDING_MODEL,
        embedding_dimensions=DIM,
        embedding_batch_size=8,
        max_retries=1,
        retry_base_delay_s=0.0,
        data_dir=tmp_path / "data",
        chroma_dir=tmp_path / "chroma",
        collection_name="test_kb",
        handoff_dir=tmp_path / "handoffs",
        feedback_file=tmp_path / "feedback" / "feedback.jsonl",
        chunk_size=320,
        chunk_overlap=60,
        top_k=3,
        candidate_k=8,
        min_retrieval_similarity=0.35,
        min_supporting_chunks=1,
        max_turns_before_escalation=6,
        frustration_streak_threshold=2,
        frustration_score_threshold=0.6,
        sensitive_mode="actions_only",
    )
    values.update(overrides)
    return Settings(**values)


DEFAULT_PERSONA = {
    "persona": "Technical Expert",
    "confidence": 0.9,
    "reasoning": "Uses API vocabulary.",
    "signals": ["api", "token"],
    "frustration_score": 0.0,
    "wants_human": False,
}

DEFAULT_GENERATION = {
    "answer": "Clear the site cookies for app.nimbusdesk.com, then sign in again. [S1]",
    "grounded": True,
    "answerable_from_context": True,
    "confidence": 0.88,
    "citations": [{"source": "S1", "section": "Cookies"}],
    "steps": ["Open browser settings", "Clear cookies for the support portal", "Sign in again"],
    "needs_escalation": False,
    "escalation_reason": "",
}

DEFAULT_HANDOFF = {
    "issue_summary": "Customer reports duplicate charges and requests a refund.",
    "issue_category": "billing",
    "severity": "high",
    "recommended_next_steps": [
        "Verify invoices and processor settlement records.",
        "Review refund eligibility without promising an outcome.",
    ],
    "recommendation": "Billing Operations should review and reply with next steps.",
}


class ScriptedLLM:
    """Routes structured calls by schema and returns deep-copied canned JSON."""

    def __init__(
        self,
        *,
        persona: dict[str, Any] | None = None,
        generation: dict[str, Any] | None = None,
        handoff: dict[str, Any] | None = None,
    ) -> None:
        self.persona_response = copy.deepcopy(persona or DEFAULT_PERSONA)
        self.generation_response = copy.deepcopy(generation or DEFAULT_GENERATION)
        self.handoff_response = copy.deepcopy(
            DEFAULT_HANDOFF if handoff is None else handoff
        )
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self,
        *,
        prompt: str,
        system_instruction: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "prompt": prompt,
                "system_instruction": system_instruction,
                "schema": schema,
                "temperature": temperature,
            }
        )
        if schema is PERSONA_SCHEMA:
            return copy.deepcopy(self.persona_response)
        if schema is GENERATION_SCHEMA:
            return copy.deepcopy(self.generation_response)
        if schema is HANDOFF_SCHEMA:
            return copy.deepcopy(self.handoff_response)
        raise AssertionError(f"Unexpected schema: {schema.get('title') or schema}")

    def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str,
        temperature: float = 0.2,
    ) -> str:
        return "unused"

    def called_with(self, schema: dict[str, Any]) -> bool:
        return any(call["schema"] is schema for call in self.calls)


def make_chunk(**overrides: Any) -> RetrievedChunk:
    values: dict[str, Any] = dict(
        chunk_id="cookies.md#000",
        text="To clear cookies, open browser settings and remove site data for the portal.",
        source="browser_troubleshooting.md",
        title="Browser Troubleshooting",
        section="Clearing cookies",
        page=None,
        chunk_index=0,
        score=0.82,
        dense_score=0.8,
        lexical_score=0.5,
    )
    values.update(overrides)
    return RetrievedChunk(**values)


class StubKnowledgeBase:
    """Small KB stand-in so orchestration tests do not depend on Chroma."""

    def __init__(
        self,
        settings: Settings,
        chunks: list[RetrievedChunk] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.settings = settings
        self.chunks = [make_chunk()] if chunks is None else list(chunks)
        self.error = error

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        if self.error is not None:
            raise self.error
        return self.chunks[: (top_k or self.settings.top_k)]

    def supporting_chunks(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return [
            chunk
            for chunk in chunks
            if chunk.score >= self.settings.min_retrieval_similarity
        ]

    def stats(self) -> dict[str, Any]:
        return {
            "chunk_count": len(self.chunks),
            "document_count": 1,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimensions": DIM,
            "chunk_size": self.settings.chunk_size,
            "chunk_overlap": self.settings.chunk_overlap,
            "built_at": "2026-01-01T00:00:00+00:00",
        }

    def staleness_reason(self) -> str | None:
        return None


@pytest.fixture
def scripted_llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def agent_factory(tmp_path: Path):
    def factory(
        *,
        llm: ScriptedLLM | None = None,
        kb: StubKnowledgeBase | None = None,
        chunks: list[RetrievedChunk] | None = None,
        kb_error: Exception | None = None,
        **settings_overrides: Any,
    ) -> tuple[SupportAgent, ScriptedLLM, StubKnowledgeBase]:
        settings = make_settings(tmp_path, **settings_overrides)
        llm = llm or ScriptedLLM()
        kb = kb or StubKnowledgeBase(settings, chunks=chunks, error=kb_error)
        agent = SupportAgent(
            settings=settings,
            knowledge_base=kb,
            classifier=PersonaClassifier(llm),
            generator=ResponseGenerator(llm),
            policy=EscalationPolicy(EscalationConfig.from_settings(settings)),
            handoff_builder=HandoffBuilder(llm),
            sensitive_detector=SensitiveTopicDetector(
                mode=settings.sensitive_mode,
                extra_terms=settings.extra_sensitive_terms,
            ),
        )
        return agent, llm, kb

    return factory


CORPUS = {
    "api_authentication.md": """# API Authentication

## Bearer tokens

Every API request must include an Authorization header of the form
`Authorization: Bearer <token>`. Tokens are scoped to a workspace. A missing or
expired bearer token returns HTTP 401 with error code `auth_token_expired`.
Generate a new access token with the OAuth client credentials flow and retry.

## Rate limiting

Requests above the plan limit return HTTP 429 with a `Retry-After` header.
""",
    "billing_refunds.md": """# Billing, Invoices, and Refunds

## Duplicate charges

A duplicate charge usually means two invoices were generated for the same
subscription period after a plan change. Finance Operations reviews the invoice
and processor settlement records before any credit is approved.

## Refund policy

Refunds are reviewed case by case within 5 business days. Support agents cannot
approve or promise a refund in chat.
""",
    "browser_troubleshooting.md": """# Browser Troubleshooting

## Clearing cookies

If a support portal page will not load, clear cookies and site data for
`app.nimbusdesk.com`, close all tabs, and sign in again. Cached service workers
can also be removed from the browser developer tools.

## Supported browsers

Use the current version of Chrome, Firefox, Edge, or Safari.
""",
    "password_reset.txt": """NimbusDesk Password Reset Guide
===============================

1. Opening the reset page
Use the "Forgot password" link on the sign-in screen.

2. Expired reset links
Password reset links expire after 30 minutes. Request a new link from the
sign-in page if the link is expired.

3. SSO accounts
Workspaces using SAML SSO must reset credentials with their identity provider.
""",
}


def create_corpus(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, content in CORPUS.items():
        (data_dir / name).write_text(content, encoding="utf-8")
