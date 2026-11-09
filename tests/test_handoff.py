"""Human handoff construction and persistence tests."""

from __future__ import annotations

import json
from pathlib import Path

from src.handoff import HANDOFF_SCHEMA, HandoffBuilder, extract_attempted_steps, save_handoff
from src.llm import LLMError
from src.models import (
    EscalationDecision,
    EscalationReason,
    Persona,
    PersonaResult,
    Session,
    Turn,
)
from tests.conftest import ScriptedLLM, make_chunk


def _session() -> Session:
    session = Session(session_id="S-TEST0001")
    session.add_turn(
        Turn(
            role="user",
            content="My billing statement has duplicate charges. I already cleared the cache and restarted the browser.",
            persona=Persona.FRUSTRATED.value,
        )
    )
    session.add_turn(
        Turn(
            role="assistant",
            content="I'm sorry. This needs our billing team.",
            persona=Persona.FRUSTRATED.value,
        )
    )
    session.add_turn(
        Turn(
            role="user",
            content="I demand an immediate refund!",
            persona=Persona.FRUSTRATED.value,
        )
    )
    session.turn_count = 3
    session.frustration_streak = 2
    session.unresolved_turns = 2
    return session


def _persona() -> PersonaResult:
    return PersonaResult(
        persona=Persona.FRUSTRATED,
        confidence=0.93,
        reasoning="Angry, repeated attempts.",
        frustration_score=0.88,
        wants_human=True,
    )


def _decision() -> EscalationDecision:
    return EscalationDecision(
        escalate=True,
        reasons=[
            EscalationReason(
                code="sensitive_billing_dispute",
                label="Billing dispute or refund request",
                detail="Matched 'demand an immediate refund'; requires Finance Operations.",
                severity="high",
            )
        ],
        sensitive_category="billing_dispute",
    )


def _sources():
    return [
        make_chunk(
            source="refund_and_dispute_policy.md",
            title="Refund and Dispute Policy",
            section="Refund eligibility",
            score=0.71,
        ),
        make_chunk(
            source="billing_policies.txt",
            title="Billing Policies",
            section="2. SEATS AND PRORATION",
            score=0.66,
        ),
    ]


def test_deterministic_handoff_contains_every_required_field(tmp_path: Path) -> None:
    handoff = HandoffBuilder(None).build(
        session=_session(),
        persona_result=_persona(),
        decision=_decision(),
        sources=_sources(),
        ticket_id="HD-20260101-ABC123",
        latest_message="I demand an immediate refund!",
    )

    data = handoff.to_dict()
    assert data["ticket_id"] == "HD-20260101-ABC123"
    assert data["session_id"] == "S-TEST0001"
    assert data["persona"] == "Frustrated User"
    assert data["persona_confidence"] == 0.93
    assert data["issue_category"] == "billing"
    assert data["severity"] == "high"
    assert data["documents_used"] == ["refund_and_dispute_policy.md", "billing_policies.txt"]
    assert len(data["retrieved_sources"]) == 2
    assert any("cleared the cache" in step.lower() for step in data["attempted_steps"])
    assert len(data["conversation_history"]) == 3
    assert data["recommended_next_steps"]
    assert "billing" in data["recommendation"]
    assert data["customer_context"]["frustration_score"] == 0.88
    assert data["customer_context"]["wants_human"] is True
    assert data["latest_message"] == "I demand an immediate refund!"
    assert data["escalation_reasons"][0]["code"] == "sensitive_billing_dispute"
    assert "Initial report" in data["issue"]


def test_handoff_serialises_to_json_and_markdown(tmp_path: Path) -> None:
    handoff = HandoffBuilder(None).build(
        session=_session(),
        persona_result=_persona(),
        decision=_decision(),
        sources=_sources(),
        ticket_id="HD-20260101-ABC123",
        latest_message="I demand an immediate refund!",
    )

    parsed = json.loads(handoff.to_json())
    assert parsed["ticket_id"] == "HD-20260101-ABC123"

    markdown = handoff.to_markdown()
    assert markdown.startswith("# Human Handoff — HD-20260101-ABC123")
    assert "## Conversation history" in markdown
    assert "## Attempted steps" in markdown
    assert "## Recommended next steps" in markdown
    assert "Frustrated User" in markdown


def test_save_handoff_writes_json_and_markdown(tmp_path: Path) -> None:
    handoff = HandoffBuilder(None).build(
        session=_session(),
        persona_result=_persona(),
        decision=_decision(),
        sources=_sources(),
        ticket_id="HD-20260101-ABC123",
        latest_message="I demand an immediate refund!",
    )

    paths = save_handoff(handoff, tmp_path / "handoffs")

    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()
    assert json.loads(Path(paths["json"]).read_text(encoding="utf-8"))["ticket_id"] == (
        "HD-20260101-ABC123"
    )
    assert "HD-20260101-ABC123" in Path(paths["markdown"]).read_text(encoding="utf-8")


def test_llm_enrichment_overrides_issue_and_recommendations() -> None:
    llm = ScriptedLLM(
        handoff={
            "issue_summary": "Customer was charged twice for one subscription and wants a refund.",
            "issue_category": "billing",
            "severity": "high",
            "recommended_next_steps": [
                "Compare the two invoices and processor settlements.",
                "Apply the refund policy and reply with a timeline.",
            ],
            "recommendation": "Finance Operations owns the review.",
        }
    )

    handoff = HandoffBuilder(llm).build(
        session=_session(),
        persona_result=_persona(),
        decision=_decision(),
        sources=_sources(),
        ticket_id="HD-20260101-ABC123",
        latest_message="I demand an immediate refund!",
    )

    assert handoff.issue == "Customer was charged twice for one subscription and wants a refund."
    assert handoff.recommendation == "Finance Operations owns the review."
    assert handoff.recommended_next_steps == [
        "Compare the two invoices and processor settlements.",
        "Apply the refund policy and reply with a timeline.",
    ]
    assert llm.called_with(HANDOFF_SCHEMA)


def test_invalid_enrichment_fields_fall_back_to_deterministic_values() -> None:
    llm = ScriptedLLM(
        handoff={
            "issue_summary": "   ",
            "issue_category": "not-a-category",
            "severity": "catastrophic",
            "recommended_next_steps": [],
            "recommendation": "Human review.",
        }
    )

    handoff = HandoffBuilder(llm).build(
        session=_session(),
        persona_result=_persona(),
        decision=_decision(),
        sources=_sources(),
        ticket_id="HD-20260101-ABC123",
        latest_message="I demand an immediate refund!",
    )

    assert "Initial report" in handoff.issue
    assert handoff.issue_category == "billing"
    assert handoff.severity == "high"
    assert handoff.recommended_next_steps  # falls back to the billing playbook


def test_handoff_enrichment_failure_is_non_fatal() -> None:
    class FailingLLM(ScriptedLLM):
        def generate_json(self, **kwargs):
            raise LLMError("quota exhausted")

    handoff = HandoffBuilder(FailingLLM()).build(
        session=_session(),
        persona_result=_persona(),
        decision=_decision(),
        sources=_sources(),
        ticket_id="HD-20260101-ABC123",
        latest_message="I demand an immediate refund!",
    )

    assert handoff.issue_category == "billing"
    assert handoff.recommendation


def test_retrieval_gap_category_when_documentation_is_missing() -> None:
    decision = EscalationDecision(
        escalate=True,
        reasons=[
            EscalationReason(
                code="low_retrieval_confidence",
                label="Low retrieval confidence",
                detail="Top score 0.18.",
                severity="high",
            )
        ],
    )
    handoff = HandoffBuilder(None).build(
        session=_session(),
        persona_result=_persona(),
        decision=decision,
        sources=[],
        ticket_id="HD-20260101-XYZ789",
        latest_message="Can you deliver a welcome kit to Antarctica?",
    )

    assert handoff.issue_category == "retrieval_gap"
    assert handoff.documents_used == []
    assert handoff.recommended_next_steps == [
        "Search internal runbooks and the product documentation for the reported symptom.",
        "Ask the customer for environment details, exact error text, and timestamps in UTC.",
        "If this is a recurrence, open a knowledge-base gap ticket with the missing scenario.",
    ]


def test_attempted_steps_are_extracted_and_deduplicated() -> None:
    turns = [
        Turn(role="user", content="I already tried clearing cookies and restarting the browser."),
        Turn(role="assistant", content="Thanks."),
        Turn(role="user", content="We've checked the DNS settings already."),
        Turn(role="user", content="I already tried clearing cookies and restarting the browser."),
    ]

    steps = extract_attempted_steps(turns)

    assert steps[0].startswith("I already tried clearing cookies")
    assert any("DNS" in step for step in steps)
    assert len(steps) == len({step.lower() for step in steps})


def test_long_conversation_is_truncated_with_a_note() -> None:
    session = _session()
    for index in range(25):
        session.add_turn(
            Turn(role="user", content=f"Follow-up {index}", persona=Persona.FRUSTRATED.value)
        )

    handoff = HandoffBuilder(None).build(
        session=session,
        persona_result=_persona(),
        decision=_decision(),
        sources=_sources(),
        ticket_id="HD-20260101-ABC123",
        latest_message="Follow-up 24",
    )

    assert len(handoff.conversation_history) == 21
    assert handoff.conversation_history[0]["role"] == "system"
    assert "omitted" in handoff.conversation_history[0]["content"]
