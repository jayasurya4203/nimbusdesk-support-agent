"""End-to-end orchestration tests for the support agent."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.generator import GENERATION_SCHEMA
from src.handoff import HANDOFF_SCHEMA
from src.models import Persona
from src.persona import PERSONA_SCHEMA
from tests.conftest import ScriptedLLM, make_chunk

TICKET_RE = re.compile(r"HD-\d{8}-[0-9A-F]{6}")


def _persona(
    persona: Persona = Persona.FRUSTRATED,
    *,
    frustration: float = 0.8,
    wants_human: bool = False,
    confidence: float = 0.9,
) -> dict:
    return {
        "persona": persona.value,
        "confidence": confidence,
        "reasoning": "Test persona.",
        "signals": ["test"],
        "frustration_score": frustration,
        "wants_human": wants_human,
    }


def test_frustrated_cookie_question_gets_an_answer_with_sources(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.FRUSTRATED))
    agent, _, kb = agent_factory(llm=llm)
    session = agent.new_session()

    reply = agent.respond(
        session,
        "Where is the guide to clear cookies? It's been an hour and nothing is loading!",
    )

    assert reply.escalation.escalate is False
    assert reply.persona.persona is Persona.FRUSTRATED
    assert reply.persona.frustration_score == 0.8
    assert reply.message.startswith("Clear the site cookies")
    assert reply.sources and reply.sources[0].source == "browser_troubleshooting.md"
    assert reply.generation is not None
    assert reply.generation.citations
    assert reply.forced_persona is False
    assert session.turn_count == 1
    assert session.escalated is False
    assert session.attempted_steps
    assert session.cited_sources
    assert reply.timings_ms["classify_ms"] >= 0
    assert reply.timings_ms["retrieval_ms"] >= 0
    assert reply.timings_ms["generate_ms"] >= 0
    assert reply.to_dict()["message"] == reply.message


def test_technical_question_uses_technical_prompt(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.TECHNICAL, frustration=0.0))
    agent, _, _ = agent_factory(llm=llm)

    reply = agent.respond(
        agent.new_session(),
        "What are the header parameter requirements for your bearer token implementation?",
    )

    assert reply.persona.persona is Persona.TECHNICAL
    assert reply.escalation.escalate is False
    generation_call = [call for call in llm.calls if call["schema"] is GENERATION_SCHEMA][-1]
    assert "**Root cause**" in generation_call["system_instruction"]


def test_executive_question_uses_executive_prompt(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.EXECUTIVE, frustration=0.0))
    agent, _, _ = agent_factory(llm=llm)

    reply = agent.respond(
        agent.new_session(),
        "Our operational uptime is decreasing. What is the resolution timeline?",
    )

    assert reply.persona.persona is Persona.EXECUTIVE
    generation_call = [call for call in llm.calls if call["schema"] is GENERATION_SCHEMA][-1]
    assert "bottom line" in generation_call["system_instruction"]


def test_forced_persona_overrides_classification(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.TECHNICAL, frustration=0.0))
    agent, _, _ = agent_factory(llm=llm)

    reply = agent.respond(
        agent.new_session(),
        "Please summarise the current status.",
        forced_persona=Persona.EXECUTIVE,
    )

    assert reply.persona.persona is Persona.EXECUTIVE
    assert reply.persona.source == "manual"
    assert reply.forced_persona is True
    assert not llm.called_with(PERSONA_SCHEMA)


def test_refund_demand_escalates_and_writes_a_complete_handoff(
    agent_factory, tmp_path: Path
) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.FRUSTRATED, frustration=0.9))
    agent, _, _ = agent_factory(llm=llm)
    session = agent.new_session()

    reply = agent.respond(
        session,
        "My billing statement has unexpected duplicate charges. I demand an immediate refund!",
    )

    assert reply.escalation.escalate is True
    assert "sensitive_billing_dispute" in reply.escalation.reason_codes
    assert reply.escalation.severity == "high"
    assert reply.generation is None
    assert not llm.called_with(GENERATION_SCHEMA)
    assert reply.handoff is not None
    assert TICKET_RE.fullmatch(reply.handoff["ticket_id"])
    assert reply.handoff["persona"] == "Frustrated User"
    assert reply.handoff["issue_category"] == "billing"
    assert reply.handoff["issue"]
    assert reply.handoff["documents_used"] == ["browser_troubleshooting.md"]
    assert reply.handoff["conversation_history"]
    assert reply.handoff["escalation_reasons"]
    assert reply.handoff["attempted_steps"] == []
    assert reply.handoff["recommended_next_steps"]
    assert TICKET_RE.search(reply.message)
    assert session.escalated is True
    assert session.handoff == reply.handoff

    paths = reply.handoff_paths or {}
    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()
    assert json.loads(Path(paths["json"]).read_text(encoding="utf-8"))["ticket_id"] == (
        reply.handoff["ticket_id"]
    )
    assert llm.called_with(HANDOFF_SCHEMA)


def test_follow_up_after_escalation_returns_ticket_status(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.FRUSTRATED, frustration=0.9))
    agent, _, _ = agent_factory(llm=llm)
    session = agent.new_session()

    first = agent.respond(session, "I demand an immediate refund for duplicate charges!")
    ticket = first.handoff["ticket_id"]
    second = agent.respond(session, "Any update on this? This is urgent!")

    assert second.escalation.escalate is True
    assert second.escalation.reason_codes == ["already_escalated"]
    assert ticket in second.message
    assert second.handoff == first.handoff
    assert second.handoff_paths == first.handoff_paths
    assert session.escalated is True
    assert session.turn_count == 2


def test_low_retrieval_confidence_escalates_without_generating(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.TECHNICAL, frustration=0.0))
    llm.handoff_response = {}
    agent, _, _ = agent_factory(
        llm=llm,
        chunks=[make_chunk(score=0.12, dense_score=0.12, lexical_score=0.0)],
    )

    reply = agent.respond(
        agent.new_session(),
        "Can you ship a physical welcome kit to our Antarctic research station?",
    )

    assert reply.escalation.escalate is True
    assert "low_retrieval_confidence" in reply.escalation.reason_codes
    assert reply.generation is None
    assert not llm.called_with(GENERATION_SCHEMA)
    assert reply.handoff["issue_category"] == "retrieval_gap"


def test_repeated_dissatisfaction_escalates_on_the_second_negative_turn(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.FRUSTRATED, frustration=0.9))
    agent, _, _ = agent_factory(llm=llm)
    session = agent.new_session()

    first = agent.respond(session, "The CSV export is not working and I'm getting frustrated!")
    assert first.escalation.escalate is False
    assert session.frustration_streak == 1

    second = agent.respond(session, "still not working, nothing works, this is ridiculous!")

    assert second.escalation.escalate is True
    assert "repeated_dissatisfaction" in second.escalation.reason_codes
    assert session.frustration_streak == 2
    assert second.handoff is not None


def test_explicit_human_request_escalates(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.TECHNICAL, frustration=0.2, wants_human=True))
    agent, _, _ = agent_factory(llm=llm)

    reply = agent.respond(agent.new_session(), "I need to speak to a human agent about this.")

    assert reply.escalation.escalate is True
    assert "human_requested" in reply.escalation.reason_codes
    assert reply.generation is None


def test_retrieval_failure_escalates_safely(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.TECHNICAL, frustration=0.0))
    llm.handoff_response = {}
    agent, _, _ = agent_factory(llm=llm, kb_error=RuntimeError("vector store offline"))

    reply = agent.respond(agent.new_session(), "How do I reset my password?")

    assert reply.escalation.escalate is True
    assert reply.escalation.reason_codes == ["retrieval_error"]
    assert reply.sources == []
    assert reply.generation is None
    assert reply.handoff["issue_category"] == "retrieval_gap"
    assert reply.handoff["documents_used"] == []


def test_unanswerable_generation_escalates(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.TECHNICAL, frustration=0.0))
    llm.generation_response = {
        "answer": "I could not find documented guidance for that.",
        "grounded": False,
        "answerable_from_context": False,
        "confidence": 0.1,
        "citations": [],
        "steps": [],
        "needs_escalation": False,
        "escalation_reason": "No matching documentation.",
    }
    llm.handoff_response = {}
    agent, _, _ = agent_factory(llm=llm)

    reply = agent.respond(agent.new_session(), "Do you support quantum teleportation?")

    assert reply.escalation.escalate is True
    assert "insufficient_grounding" in reply.escalation.reason_codes
    assert reply.generation is not None
    assert reply.handoff["issue_category"] == "retrieval_gap"


def test_uncited_generation_escalates(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.TECHNICAL, frustration=0.0))
    llm.generation_response = {
        "answer": "Reset links last 30 minutes.",
        "grounded": True,
        "answerable_from_context": True,
        "confidence": 0.9,
        "citations": [],
        "steps": [],
        "needs_escalation": False,
        "escalation_reason": "",
    }
    llm.handoff_response = {}
    agent, _, _ = agent_factory(llm=llm)

    reply = agent.respond(agent.new_session(), "How long do reset links last?")

    assert reply.escalation.escalate is True
    assert "insufficient_grounding" in reply.escalation.reason_codes


def test_resolution_message_resets_frustration(agent_factory) -> None:
    llm = ScriptedLLM(persona=_persona(Persona.FRUSTRATED, frustration=0.8))
    agent, _, _ = agent_factory(llm=llm)
    session = agent.new_session()

    agent.respond(session, "The export is not working!")
    assert session.frustration_streak == 1

    llm.persona_response = _persona(Persona.FRUSTRATED, frustration=0.0)
    reply = agent.respond(session, "Thanks, that worked — it's fixed now.")

    assert reply.escalation.escalate is False
    assert session.frustration_streak == 0
    assert session.resolved is True


def test_blank_messages_are_rejected(agent_factory) -> None:
    import pytest

    agent, _, _ = agent_factory()
    with pytest.raises(ValueError):
        agent.respond(agent.new_session(), "   ")
