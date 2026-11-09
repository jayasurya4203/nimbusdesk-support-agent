"""Shared data structures for the agent, UI, and tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utc_now()).isoformat(timespec="seconds")


class Persona(str, Enum):
    TECHNICAL = "Technical Expert"
    FRUSTRATED = "Frustrated User"
    EXECUTIVE = "Business Executive"

    @classmethod
    def values(cls) -> list[str]:
        return [p.value for p in cls]

    @classmethod
    def from_label(cls, label: str) -> "Persona":
        normalized = label.strip().lower().replace("_", " ")
        for persona in cls:
            if persona.value.lower() == normalized:
                return persona
        aliases = {
            "technical": cls.TECHNICAL,
            "tech": cls.TECHNICAL,
            "developer": cls.TECHNICAL,
            "frustrated": cls.FRUSTRATED,
            "angry": cls.FRUSTRATED,
            "executive": cls.EXECUTIVE,
            "business": cls.EXECUTIVE,
            "exec": cls.EXECUTIVE,
        }
        if normalized in aliases:
            return aliases[normalized]
        raise ValueError(f"Unknown persona: {label!r}")


@dataclass
class PersonaResult:
    persona: Persona
    confidence: float
    reasoning: str = ""
    signals: list[str] = field(default_factory=list)
    source: str = "llm"
    frustration_score: float = 0.0
    wants_human: bool = False
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "persona": self.persona.value,
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "signals": list(self.signals),
            "source": self.source,
            "frustration_score": round(self.frustration_score, 3),
            "wants_human": self.wants_human,
            "latency_ms": self.latency_ms,
        }


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    source: str
    title: str = ""
    section: str = ""
    page: int | None = None
    chunk_index: int = 0
    score: float = 0.0
    dense_score: float = 0.0
    lexical_score: float = 0.0

    @property
    def citation(self) -> str:
        location = f"p. {self.page}" if self.page else self.section
        return f"{self.title or self.source} — {location}" if location else self.source

    @property
    def page_label(self) -> str:
        return f"Page {self.page}" if self.page else "—"

    def to_dict(self, include_text: bool = True) -> dict[str, Any]:
        data = {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "title": self.title,
            "section": self.section,
            "page": self.page,
            "chunk_index": self.chunk_index,
            "score": round(self.score, 4),
            "dense_score": round(self.dense_score, 4),
            "lexical_score": round(self.lexical_score, 4),
        }
        if include_text:
            data["text"] = self.text
        return data


@dataclass
class Turn:
    role: str
    content: str
    persona: str | None = None
    timestamp: str = field(default_factory=iso)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "persona": self.persona,
            "timestamp": self.timestamp,
            "meta": self.meta,
        }


@dataclass
class EscalationReason:
    code: str
    label: str
    detail: str
    severity: str = "medium"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "label": self.label,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class EscalationDecision:
    escalate: bool = False
    reasons: list[EscalationReason] = field(default_factory=list)
    sensitive_category: str | None = None

    @property
    def severity(self) -> str:
        if any(reason.severity == "high" for reason in self.reasons):
            return "high"
        return "medium" if self.reasons else "low"

    @property
    def primary_reason(self) -> EscalationReason | None:
        return self.reasons[0] if self.reasons else None

    @property
    def reason_codes(self) -> list[str]:
        return [reason.code for reason in self.reasons]

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalate": self.escalate,
            "severity": self.severity,
            "sensitive_category": self.sensitive_category,
            "reasons": [reason.to_dict() for reason in self.reasons],
        }


@dataclass
class GenerationResult:
    answer: str
    grounded: bool = True
    answerable: bool = True
    confidence: float = 0.0
    citations: list[dict[str, str]] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    needs_escalation: bool = False
    escalation_reason: str = ""
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "grounded": self.grounded,
            "answerable": self.answerable,
            "confidence": round(self.confidence, 3),
            "citations": list(self.citations),
            "steps": list(self.steps),
            "needs_escalation": self.needs_escalation,
            "escalation_reason": self.escalation_reason,
            "latency_ms": self.latency_ms,
        }


@dataclass
class Handoff:
    ticket_id: str
    session_id: str
    created_at: str
    persona: str
    persona_confidence: float
    persona_reasoning: str
    issue: str
    issue_category: str
    documents_used: list[str]
    retrieved_sources: list[dict[str, Any]]
    attempted_steps: list[str]
    conversation_history: list[dict[str, Any]]
    recommendation: str
    recommended_next_steps: list[str]
    escalation_reasons: list[dict[str, str]]
    severity: str
    frustration_score: float
    turn_count: int
    latest_message: str
    wants_human: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "severity": self.severity,
            "persona": self.persona,
            "persona_confidence": round(self.persona_confidence, 3),
            "persona_reasoning": self.persona_reasoning,
            "issue": self.issue,
            "issue_category": self.issue_category,
            "documents_used": self.documents_used,
            "retrieved_sources": self.retrieved_sources,
            "attempted_steps": self.attempted_steps,
            "conversation_history": self.conversation_history,
            "recommendation": self.recommendation,
            "recommended_next_steps": self.recommended_next_steps,
            "escalation_reasons": self.escalation_reasons,
            "customer_context": {
                "frustration_score": round(self.frustration_score, 3),
                "turn_count": self.turn_count,
                "wants_human": self.wants_human,
            },
            "latest_message": self.latest_message,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def to_markdown(self) -> str:
        lines = [
            f"# Human Handoff — {self.ticket_id}",
            "",
            f"- **Created:** {self.created_at}",
            f"- **Severity:** {self.severity}",
            f"- **Persona:** {self.persona} (confidence {self.persona_confidence:.0%})",
            f"- **Issue category:** {self.issue_category}",
            f"- **Turns:** {self.turn_count}",
            "",
            "## Issue",
            self.issue,
            "",
            "## Escalation reasons",
        ]
        lines += [f"- **{r['label']}** ({r['code']}): {r['detail']}" for r in self.escalation_reasons]
        lines += ["", "## Documents used"]
        lines += [f"- {doc}" for doc in self.documents_used] or ["- None"]
        lines += ["", "## Attempted steps"]
        lines += [f"- {step}" for step in self.attempted_steps] or ["- None recorded"]
        lines += ["", "## Recommended next steps"]
        lines += [f"{i}. {step}" for i, step in enumerate(self.recommended_next_steps, 1)]
        lines += ["", "## Recommendation", self.recommendation, "", "## Conversation history"]
        for turn in self.conversation_history:
            content = str(turn.get("content", "")).replace("\n", " ")
            lines.append(f"- **{turn.get('role', '?').title()}** ({turn.get('timestamp', '')}): {content}")
        return "\n".join(lines)


@dataclass
class Session:
    session_id: str
    created_at: str = field(default_factory=iso)
    history: list[Turn] = field(default_factory=list)
    persona: Persona | None = None
    persona_result: PersonaResult | None = None
    turn_count: int = 0
    frustration_streak: int = 0
    unresolved_turns: int = 0
    escalated: bool = False
    escalated_at: str | None = None
    handoff: dict[str, Any] | None = None
    handoff_paths: dict[str, str] | None = None
    attempted_steps: list[str] = field(default_factory=list)
    cited_sources: list[str] = field(default_factory=list)
    last_retrieval_score: float = 0.0
    resolved: bool = False

    def add_turn(self, turn: Turn) -> None:
        self.history.append(turn)

    def recent_history(self, limit: int = 8) -> list[Turn]:
        return self.history[-limit:]

    def remember_steps(self, steps: list[str]) -> None:
        for step in steps:
            cleaned = " ".join(step.split()).strip(" -•")
            if cleaned and cleaned.lower() not in {s.lower() for s in self.attempted_steps}:
                self.attempted_steps.append(cleaned)

    def remember_sources(self, sources: list[str]) -> None:
        for source in sources:
            if source and source not in self.cited_sources:
                self.cited_sources.append(source)

    def to_summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "persona": self.persona.value if self.persona else None,
            "turn_count": self.turn_count,
            "frustration_streak": self.frustration_streak,
            "unresolved_turns": self.unresolved_turns,
            "escalated": self.escalated,
            "escalated_at": self.escalated_at,
            "handoff": self.handoff,
            "attempted_steps": list(self.attempted_steps),
            "cited_sources": list(self.cited_sources),
        }


@dataclass
class AgentReply:
    message: str
    session_id: str
    persona: PersonaResult
    sources: list[RetrievedChunk] = field(default_factory=list)
    escalation: EscalationDecision = field(default_factory=EscalationDecision)
    handoff: dict[str, Any] | None = None
    handoff_paths: dict[str, str] | None = None
    generation: GenerationResult | None = None
    retrieval_confidence: float = 0.0
    response_confidence: float = 0.0
    timings_ms: dict[str, int] = field(default_factory=dict)
    forced_persona: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "session_id": self.session_id,
            "persona": self.persona.to_dict(),
            "sources": [chunk.to_dict(include_text=False) for chunk in self.sources],
            "escalation": self.escalation.to_dict(),
            "handoff": self.handoff,
            "handoff_paths": self.handoff_paths,
            "generation": self.generation.to_dict() if self.generation else None,
            "retrieval_confidence": round(self.retrieval_confidence, 4),
            "response_confidence": round(self.response_confidence, 4),
            "timings_ms": self.timings_ms,
            "forced_persona": self.forced_persona,
        }
