"""Sensitive-topic detection and escalation policy tests."""

from __future__ import annotations

import pytest

from src.config import Settings
from src.escalator import (
    EscalationConfig,
    EscalationContext,
    EscalationPolicy,
    SensitiveTopicDetector,
    customer_friendly_reason,
    detect_human_request,
    persona_escalation_notice,
)
from src.models import EscalationDecision, EscalationReason, GenerationResult, Persona, PersonaResult


def _persona(
    persona: Persona = Persona.TECHNICAL, frustration: float = 0.0
) -> PersonaResult:
    return PersonaResult(
        persona=persona,
        confidence=0.9,
        source="llm",
        frustration_score=frustration,
    )


def _generation(**overrides) -> GenerationResult:
    values = dict(
        answer="Clear cookies and sign in again.",
        grounded=True,
        answerable=True,
        confidence=0.85,
        citations=[{"source": "browser_troubleshooting.txt", "section": "Cookies"}],
        steps=["Clear cookies"],
        needs_escalation=False,
        escalation_reason="",
    )
    values.update(overrides)
    return GenerationResult(**values)


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("I demand an immediate refund for the duplicate charges on my invoice.", "billing_dispute"),
        ("Please reverse this unexpected charge today.", "billing_dispute"),
        ("I will file a chargeback if this is not fixed.", "billing_dispute"),
        ("My attorney will send a demand letter about this contract.", "legal"),
        ("Please delete my account and all workspace data.", "account_security"),
        ("I need to transfer ownership of the workspace.", "account_security"),
        ("I want to update the credit card on file.", "payment_change"),
        ("Someone else logged in and changed my password; I think the account is compromised.", "security_incident"),
    ],
)
def test_actionable_sensitive_requests_are_detected(message: str, category: str) -> None:
    match = SensitiveTopicDetector(mode="actions_only").detect(message)

    assert match is not None
    assert match.category == category
    assert match.severity == "high"


def test_informational_billing_question_is_not_escalated_in_actions_only_mode() -> None:
    detector = SensitiveTopicDetector(mode="actions_only")

    assert detector.detect("Can you explain how refunds are processed?") is None
    assert detector.detect("Where can I download last month's invoice?") is None


def test_always_mode_escalates_informational_sensitive_mentions() -> None:
    match = SensitiveTopicDetector(mode="always").detect(
        "Can you explain how refunds are processed?"
    )

    assert match is not None
    assert match.category == "billing_dispute"
    assert match.escalated_because == "informational_mention_always_mode"


def test_custom_sensitive_terms_are_configurable() -> None:
    detector = SensitiveTopicDetector(
        mode="actions_only", extra_terms=("enterprise contract",)
    )
    match = detector.detect("This enterprise contract needs a signature.")

    assert match is not None
    assert match.category == "custom"
    assert match.escalated_because == "configured_term"


def test_sensitive_detector_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        SensitiveTopicDetector(mode="sometimes")


def test_detect_human_request() -> None:
    assert detect_human_request("I want to speak with a human")
    assert detect_human_request("please escalate this")
    assert not detect_human_request("please reset my password")


def test_policy_escalates_on_low_retrieval_confidence() -> None:
    policy = EscalationPolicy(EscalationConfig(min_similarity=0.5))
    decision = policy.evaluate(
        EscalationContext(
            message="Do you ship welcome kits to Antarctica?",
            persona=_persona(),
            retrieval_top_score=0.2,
            supporting_count=0,
            generation=None,
        )
    )

    assert decision.escalate
    assert "low_retrieval_confidence" in decision.reason_codes
    assert decision.severity == "high"


def test_policy_allows_generation_when_retrieval_is_confident() -> None:
    policy = EscalationPolicy(EscalationConfig(min_similarity=0.5))
    decision = policy.evaluate(
        EscalationContext(
            message="How do I clear cookies?",
            persona=_persona(),
            retrieval_top_score=0.82,
            supporting_count=2,
            generation=None,
        )
    )

    assert not decision.escalate
    assert decision.reasons == []


def test_policy_escalates_on_ungrounded_or_unanswerable_output() -> None:
    policy = EscalationPolicy()

    unanswerable = policy.evaluate(
        EscalationContext(
            message="What is the refund timeline?",
            persona=_persona(),
            retrieval_top_score=0.8,
            supporting_count=1,
            generation=_generation(answerable=False, answer="I could not find it."),
        )
    )
    assert "insufficient_grounding" in unanswerable.reason_codes

    ungrounded = policy.evaluate(
        EscalationContext(
            message="What is the refund timeline?",
            persona=_persona(),
            retrieval_top_score=0.8,
            supporting_count=1,
            generation=_generation(grounded=False),
        )
    )
    assert "ungrounded_response" in ungrounded.reason_codes


def test_policy_escalates_on_missing_citations() -> None:
    policy = EscalationPolicy(EscalationConfig(require_citations=True))
    decision = policy.evaluate(
        EscalationContext(
            message="How do I clear cookies?",
            persona=_persona(),
            retrieval_top_score=0.8,
            supporting_count=1,
            generation=_generation(answer="Clear cookies.", citations=[]),
        )
    )

    assert "missing_citations" in decision.reason_codes


def test_policy_honours_agent_recommended_escalation() -> None:
    policy = EscalationPolicy()
    decision = policy.evaluate(
        EscalationContext(
            message="My export failed and data is missing.",
            persona=_persona(),
            retrieval_top_score=0.8,
            supporting_count=1,
            generation=_generation(
                needs_escalation=True,
                escalation_reason="Data loss requires human investigation.",
            ),
        )
    )

    assert "llm_recommended_escalation" in decision.reason_codes
    assert decision.primary_reason is not None
    assert "Data loss" in decision.primary_reason.detail


def test_policy_escalates_on_repeated_dissatisfaction() -> None:
    policy = EscalationPolicy(
        EscalationConfig(frustration_streak_threshold=2, frustration_score_threshold=0.6)
    )
    decision = policy.evaluate(
        EscalationContext(
            message="Still not working!",
            persona=_persona(Persona.FRUSTRATED, frustration=0.9),
            retrieval_top_score=0.8,
            supporting_count=1,
            generation=_generation(),
            consecutive_negative=2,
        )
    )

    assert "repeated_dissatisfaction" in decision.reason_codes
    assert decision.severity == "high"


def test_policy_escalates_on_unresolved_long_conversation() -> None:
    policy = EscalationPolicy(EscalationConfig(max_turns=6))
    decision = policy.evaluate(
        EscalationContext(
            message="Any update?",
            persona=_persona(Persona.FRUSTRATED, frustration=0.7),
            retrieval_top_score=0.8,
            supporting_count=1,
            generation=_generation(),
            consecutive_negative=1,
            unresolved_turns=6,
        )
    )

    assert "unresolved_conversation" in decision.reason_codes


def test_policy_includes_sensitive_and_human_reasons_without_duplicates() -> None:
    policy = EscalationPolicy()
    match = SensitiveTopicDetector().detect("I demand a refund and I want a human now.")
    decision = policy.evaluate(
        EscalationContext(
            message="I demand a refund and I want a human now.",
            persona=_persona(Persona.FRUSTRATED, frustration=0.8),
            retrieval_top_score=0.8,
            supporting_count=1,
            sensitive=match,
            wants_human=True,
        )
    )

    assert "sensitive_billing_dispute" in decision.reason_codes
    assert "human_requested" in decision.reason_codes
    assert decision.sensitive_category == "billing_dispute"
    assert len(decision.reasons) == len(set(decision.reason_codes))


def test_config_from_settings_reads_every_threshold() -> None:
    settings = Settings(
        min_retrieval_similarity=0.61,
        min_supporting_chunks=2,
        max_turns_before_escalation=4,
        frustration_streak_threshold=3,
        frustration_score_threshold=0.7,
        sensitive_mode="always",
        require_citations=False,
    )
    config = EscalationConfig.from_settings(settings)

    assert config.min_similarity == 0.61
    assert config.min_supporting_chunks == 2
    assert config.max_turns == 4
    assert config.frustration_streak_threshold == 3
    assert config.frustration_score_threshold == 0.7
    assert config.sensitive_mode == "always"
    assert config.require_citations is False


def test_friendly_reasons_and_persona_notices() -> None:
    decision = EscalationDecision(
        escalate=True,
        reasons=[
            EscalationReason(
                code="sensitive_billing_dispute",
                label="Billing dispute or refund request",
                detail="customer demanded a refund",
                severity="high",
            )
        ],
        sensitive_category="billing_dispute",
    )

    assert "billing team" in customer_friendly_reason(decision)
    for persona in Persona:
        notice = persona_escalation_notice(persona, decision, "HD-20260101-ABC123")
        assert "HD-20260101-ABC123" in notice
        assert "billing disputes" not in notice.lower()
    assert "really sorry" in persona_escalation_notice(
        Persona.FRUSTRATED, decision, "HD-1"
    ).lower()
