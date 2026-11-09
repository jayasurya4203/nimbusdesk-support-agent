"""Grounded generation and citation validation tests."""

from __future__ import annotations

import pytest

from src.generator import ResponseGenerator, build_context
from src.llm import LLMError
from src.models import Persona, PersonaResult, RetrievedChunk
from tests.conftest import DEFAULT_GENERATION, ScriptedLLM, make_chunk


def _persona(persona: Persona = Persona.TECHNICAL) -> PersonaResult:
    return PersonaResult(persona=persona, confidence=0.9, source="llm")


def _chunks() -> list[RetrievedChunk]:
    return [
        make_chunk(
            chunk_id="browser_troubleshooting.txt#000",
            source="browser_troubleshooting.txt",
            title="Browser Troubleshooting",
            section="Clearing cache and cookies",
            text="Clear cookies and site data for app.nimbusdesk.io.",
        ),
        make_chunk(
            chunk_id="password_reset_guide.pdf#002",
            source="password_reset_guide.pdf",
            title="Password Reset Guide",
            section="2. Expired links",
            page=2,
            text="Reset links expire after 30 minutes.",
        ),
    ]


def test_build_context_labels_chunks_with_pages_and_sections() -> None:
    context, tag_map = build_context(_chunks())

    assert "[S1] Browser Troubleshooting | Clearing cache and cookies" in context
    assert "[S2] Password Reset Guide | page 2" in context
    assert tag_map["S2"].page == 2
    assert build_context([]) == ("(no context retrieved)", {})


def test_valid_generation_returns_verified_citations() -> None:
    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "answer": "Clear cookies [S1]. If the reset link is older than 30 minutes it has expired [S2].",
            "citations": [
                {"source": "S1", "section": "Clearing cache and cookies"},
                {"source": "S2", "section": "2. Expired links"},
            ],
            "steps": ["Clear cookies", "Request a new reset link"],
            "confidence": 1.4,
        }
    )

    result = ResponseGenerator(llm).generate(
        query="How do I fix sign-in and expired reset links?",
        persona_result=_persona(),
        chunks=_chunks(),
    )

    assert result.answerable is True
    assert result.grounded is True
    assert result.confidence == 1.0
    assert [citation["source"] for citation in result.citations] == [
        "browser_troubleshooting.txt",
        "password_reset_guide.pdf",
    ]
    assert result.citations[1]["page"] == "Page 2"
    assert result.steps == ["Clear cookies", "Request a new reset link"]


def test_citations_can_reference_a_document_name() -> None:
    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "citations": [{"source": "browser_troubleshooting.txt", "section": "cookies"}],
        }
    )

    result = ResponseGenerator(llm).generate(
        query="cookies", persona_result=_persona(), chunks=_chunks()
    )

    assert len(result.citations) == 1
    assert result.citations[0]["source"] == "browser_troubleshooting.txt"


def test_inline_citation_tags_are_accepted_when_array_is_missing() -> None:
    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "answer": "Reset links expire after 30 minutes [S2].",
            "citations": [],
        }
    )

    result = ResponseGenerator(llm).generate(
        query="How long do reset links last?",
        persona_result=_persona(),
        chunks=_chunks(),
    )

    assert result.answerable is True
    assert len(result.citations) == 1
    assert result.citations[0]["source"] == "password_reset_guide.pdf"


def test_uncited_answer_is_marked_unanswerable() -> None:
    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "answer": "Clear cookies.",
            "citations": [],
            "escalation_reason": "",
        }
    )

    result = ResponseGenerator(llm).generate(
        query="How do I clear cookies?", persona_result=_persona(), chunks=_chunks()
    )

    assert result.answerable is False
    assert result.grounded is False
    assert "could not be traced" in result.escalation_reason


def test_invalid_citation_tags_are_dropped() -> None:
    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "answer": "Clear cookies.",
            "citations": [{"source": "S99", "section": "unknown"}],
        }
    )

    result = ResponseGenerator(llm).generate(
        query="cookies", persona_result=_persona(), chunks=_chunks()
    )

    assert result.citations == []
    assert result.answerable is False


def test_generation_failure_returns_escalation_result() -> None:
    class FailingLLM(ScriptedLLM):
        def generate_json(self, **kwargs):
            raise LLMError("model unavailable")

    result = ResponseGenerator(FailingLLM()).generate(
        query="cookies", persona_result=_persona(), chunks=_chunks()
    )

    assert result.answerable is False
    assert result.needs_escalation is True
    assert "unavailable" in result.escalation_reason


def test_malformed_generation_response_is_handled() -> None:
    llm = ScriptedLLM(generation={**DEFAULT_GENERATION, "confidence": "very high"})

    result = ResponseGenerator(llm).generate(
        query="cookies", persona_result=_persona(), chunks=_chunks()
    )

    assert result.answerable is False
    assert result.needs_escalation is True
    assert "malformed" in result.escalation_reason


def test_non_list_steps_and_excess_steps_are_sanitised() -> None:
    llm = ScriptedLLM(
        generation={**DEFAULT_GENERATION, "steps": "not-a-list"}
    )
    assert (
        ResponseGenerator(llm)
        .generate(query="cookies", persona_result=_persona(), chunks=_chunks())
        .steps
        == []
    )

    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "steps": [f"Step {index}" for index in range(20)],
        }
    )
    steps = ResponseGenerator(llm).generate(
        query="cookies", persona_result=_persona(), chunks=_chunks()
    ).steps
    assert len(steps) == 8


def test_frustrated_answer_includes_steps_when_the_model_splits_them_out() -> None:
    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "answer": "Please follow these steps to clear your cookies.",
            "steps": ["Open browser settings", "Clear site data", "Sign in again"],
        }
    )

    result = ResponseGenerator(llm).generate(
        query="cookies",
        persona_result=_persona(Persona.FRUSTRATED),
        chunks=_chunks(),
    )

    assert result.answer == (
        "Please follow these steps to clear your cookies.\n\n"
        "1. Open browser settings\n2. Clear site data\n3. Sign in again"
    )


def test_numbered_steps_already_in_the_answer_are_not_duplicated() -> None:
    answer = (
        "Here is the fix:\n\n"
        "1. Open browser settings\n2. Clear site data\n3. Sign in again"
    )
    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "answer": answer,
            "steps": ["Open browser settings", "Clear site data", "Sign in again"],
        }
    )

    result = ResponseGenerator(llm).generate(
        query="cookies",
        persona_result=_persona(Persona.FRUSTRATED),
        chunks=_chunks(),
    )

    assert result.answer == answer


def test_inline_numbered_steps_are_not_duplicated() -> None:
    answer = (
        "Diagnosis: the token expired. Resolution steps: 1. Refresh the token. "
        "2. Retry the request with the new Authorization header."
    )
    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "answer": answer,
            "steps": ["Refresh the access token", "Retry with the new header"],
        }
    )

    result = ResponseGenerator(llm).generate(
        query="token",
        persona_result=_persona(Persona.TECHNICAL),
        chunks=_chunks(),
    )

    assert result.answer == answer


def test_executive_answers_keep_steps_out_of_the_body() -> None:
    llm = ScriptedLLM(
        generation={
            **DEFAULT_GENERATION,
            "answer": "Bottom line: cookies must be cleared before sign-in.",
            "steps": ["Open browser settings", "Clear site data"],
        }
    )

    result = ResponseGenerator(llm).generate(
        query="cookies",
        persona_result=_persona(Persona.EXECUTIVE),
        chunks=_chunks(),
    )

    assert result.answer == "Bottom line: cookies must be cleared before sign-in."


@pytest.mark.parametrize(
    ("persona", "expected_style"),
    [
        (Persona.TECHNICAL, "**Root cause**"),
        (Persona.FRUSTRATED, "calm, empathetic"),
        (Persona.EXECUTIVE, "bottom line"),
    ],
)
def test_persona_specific_instructions_are_sent_to_the_model(
    persona: Persona, expected_style: str
) -> None:
    llm = ScriptedLLM()

    ResponseGenerator(llm).generate(
        query="How do I clear cookies?",
        persona_result=_persona(persona),
        chunks=_chunks(),
    )

    system_instruction = llm.calls[-1]["system_instruction"]
    assert expected_style in system_instruction
    assert "Do not use outside knowledge" in system_instruction
    assert "Do not set needs_escalation for informational questions" in system_instruction
