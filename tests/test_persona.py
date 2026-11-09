"""Persona classification, friction scoring, and hysteresis tests."""

from __future__ import annotations

import pytest

from src.llm import LLMError
from src.models import Persona, Turn
from src.persona import (
    PersonaClassifier,
    estimate_frustration,
    format_history,
    rule_based_classify,
    wants_human,
)
from tests.conftest import DEFAULT_PERSONA, ScriptedLLM


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "What are the header parameter requirements for your bearer token auth implementation?",
            Persona.TECHNICAL,
        ),
        (
            "Where is the guide to clear cookies? It's been an hour and nothing is loading on your interface!",
            Persona.FRUSTRATED,
        ),
        (
            "Our operational uptime is decreasing. We need a timeline of when billing disputes are resolved.",
            Persona.EXECUTIVE,
        ),
        (
            "My billing statement has unexpected duplicate charges. I demand an immediate refund!",
            Persona.FRUSTRATED,
        ),
        (
            "Postgres connector throws error code 500 on every query and the stack trace is in the logs.",
            Persona.TECHNICAL,
        ),
        (
            "We need a board-level summary of SLA credits and revenue risk before renewal.",
            Persona.EXECUTIVE,
        ),
    ],
)
def test_rule_based_classification_of_support_scenarios(message: str, expected: Persona) -> None:
    result = rule_based_classify(message)

    assert result.persona is expected
    assert result.source == "rules"
    assert 0.0 <= result.confidence <= 1.0


def test_rule_based_classifier_defaults_to_technical_with_low_confidence() -> None:
    result = rule_based_classify("Can you ship a physical welcome kit to our office?")

    assert result.persona is Persona.TECHNICAL
    assert result.confidence == pytest.approx(0.3)
    assert result.signals == []


def test_frustration_estimate_reacts_to_intensity() -> None:
    calm = estimate_frustration("Please explain how the refund process works.")
    upset = estimate_frustration("NOTHING WORKS!!! This is ridiculous and I have waited an hour!")

    assert 0.0 <= calm < upset <= 1.0
    assert upset >= 0.5


def test_wants_human_detects_explicit_requests() -> None:
    assert wants_human("I need to speak to a human agent")
    assert wants_human("Please escalate this to your manager")
    assert not wants_human("How do I reset my password?")


def test_forced_persona_bypasses_the_model() -> None:
    llm = ScriptedLLM()
    classifier = PersonaClassifier(llm)

    result = classifier.classify(
        "bearer token 401", forced=Persona.EXECUTIVE
    )

    assert result.persona is Persona.EXECUTIVE
    assert result.source == "manual"
    assert result.confidence == 1.0
    assert not llm.calls


def test_llm_classification_is_used_when_valid() -> None:
    llm = ScriptedLLM(
        persona={
            "persona": "Frustrated User",
            "confidence": 0.88,
            "reasoning": "Repeated failure and exclamation marks.",
            "signals": ["nothing works", "waited an hour"],
            "frustration_score": 0.85,
            "wants_human": True,
        }
    )

    result = PersonaClassifier(llm).classify("nothing works after an hour!")

    assert result.persona is Persona.FRUSTRATED
    assert result.source == "llm"
    assert result.frustration_score == pytest.approx(0.85)
    assert result.wants_human is True


def test_llm_failure_falls_back_to_rules() -> None:
    class FailingLLM(ScriptedLLM):
        def generate_json(self, **kwargs):
            raise LLMError("quota exhausted")

    result = PersonaClassifier(FailingLLM()).classify(
        "The webhook signature verification fails with HMAC error 401."
    )

    assert result.persona is Persona.TECHNICAL
    assert result.source == "rules"


def test_weak_persona_switch_keeps_previous_session_persona() -> None:
    llm = ScriptedLLM(
        persona={
            "persona": "Business Executive",
            "confidence": 0.42,
            "reasoning": "Mentions a deadline.",
            "signals": ["deadline"],
            "frustration_score": 0.1,
            "wants_human": False,
        }
    )
    result = PersonaClassifier(llm).classify(
        "ok, what now?", previous=Persona.TECHNICAL
    )

    assert result.persona is Persona.TECHNICAL
    assert result.source == "session"
    assert "Kept the session persona" in result.reasoning


def test_confident_persona_switch_overrides_previous() -> None:
    llm = ScriptedLLM(
        persona={
            "persona": "Business Executive",
            "confidence": 0.91,
            "reasoning": "Explicit SLA and revenue language.",
            "signals": ["SLA", "revenue"],
            "frustration_score": 0.2,
            "wants_human": False,
        }
    )
    result = PersonaClassifier(llm).classify(
        "What SLA credits apply? This affects revenue.", previous=Persona.TECHNICAL
    )

    assert result.persona is Persona.EXECUTIVE
    assert result.source == "llm"


def test_classifier_rejects_unknown_persona_label_and_falls_back() -> None:
    llm = ScriptedLLM(persona={**DEFAULT_PERSONA, "persona": "Wizard"})

    result = PersonaClassifier(llm).classify("bearer token 401 error")

    assert result.source == "rules"
    assert result.persona is Persona.TECHNICAL


def test_history_formatting_truncates_and_orders_turns() -> None:
    turns = [
        Turn(role="user", content="first"),
        Turn(role="assistant", content="second " * 300),
    ]
    formatted = format_history(turns)

    assert formatted.startswith("User: first")
    assert "Assistant: second" in formatted
    assert "…" in formatted
    assert format_history([]) == "(no prior turns)"
