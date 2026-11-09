"""Structured human handoff summaries.

The deterministic fields are always produced, so a handoff never depends on a
second model call succeeding. When the LLM is available it adds a concise issue
summary, issue category, and recommended next steps, all validated against the
known facts before being written to disk.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .llm import LLMClient, LLMError
from .models import (
    EscalationDecision,
    Handoff,
    PersonaResult,
    RetrievedChunk,
    Session,
    Turn,
    iso,
)
from .persona import format_history

LOGGER = logging.getLogger(__name__)

HANDOFF_SCHEMA: dict = {
    "type": "OBJECT",
    "properties": {
        "issue_summary": {"type": "STRING"},
        "issue_category": {
            "type": "STRING",
            "enum": [
                "billing",
                "account_security",
                "legal",
                "security_incident",
                "technical",
                "integration",
                "retrieval_gap",
                "other",
            ],
        },
        "severity": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "recommended_next_steps": {"type": "ARRAY", "items": {"type": "STRING"}},
        "recommendation": {"type": "STRING"},
    },
    "required": [
        "issue_summary",
        "issue_category",
        "severity",
        "recommended_next_steps",
        "recommendation",
    ],
}

HANDOFF_SYSTEM_INSTRUCTION = """You are preparing a handoff ticket for a human support specialist at NimbusDesk. Summarize only what is present in the conversation and the supplied context. Do not invent facts, promise refunds, or include secrets, passwords, API keys, or card numbers.

Produce:
- issue_summary: 1-2 sentences describing the customer's problem and what they need.
- issue_category: the best matching category.
- severity: high for security, legal, or billing disputes with financial/legal risk; medium for blocked work; low for informational follow-ups.
- recommended_next_steps: 2-5 concrete internal actions for the human specialist.
- recommendation: one sentence describing the recommended resolution path.

Return only the requested JSON object."""

_ATTEMPT_RE = re.compile(
    r"(?:i|we)(?:'ve|\s+have)?\s+(?:already\s+)?(?:tried|attempted|followed|cleared|"
    r"restarted|reinstalled|reset|checked|tested|recreated|updated|rotated)\b[^.!\n]{0,140}",
    re.IGNORECASE,
)

_CATEGORY_BY_SENSITIVE = {
    "billing_dispute": "billing",
    "payment_change": "billing",
    "legal": "legal",
    "account_security": "account_security",
    "security_incident": "security_incident",
}

_NEXT_STEPS: dict[str, list[str]] = {
    "billing": [
        "Verify the workspace's invoices, payment method, and processor settlement records.",
        "Review refund or credit eligibility against the refund and dispute policy; do not promise an outcome.",
        "Reply to the customer with the investigation timeline and next update.",
    ],
    "legal": [
        "Route the ticket to Legal immediately; do not interpret the legal question.",
        "Acknowledge receipt and confirm that the appropriate team will follow up.",
        "Preserve the customer's message and any referenced documents.",
    ],
    "account_security": [
        "Verify the requester's identity through the approved ownership-verification process.",
        "Confirm whether an owner or admin is available to complete the change in-product.",
        "Perform the requested action only after verification; log the change in the audit trail.",
    ],
    "security_incident": [
        "Escalate to Security Operations and preserve timestamps and request IDs.",
        "Advise the customer to revoke exposed keys and sign out all sessions.",
        "Do not confirm or deny a breach until Security Operations validates the report.",
    ],
    "retrieval_gap": [
        "Search internal runbooks and the product documentation for the reported symptom.",
        "Ask the customer for environment details, exact error text, and timestamps in UTC.",
        "If this is a recurrence, open a knowledge-base gap ticket with the missing scenario.",
    ],
    "technical": [
        "Review the retrieved documentation and confirm the customer's environment and plan.",
        "Reproduce the symptom or inspect server-side logs using the workspace ID and request IDs.",
        "Reply with the confirmed root cause and the next diagnostic step.",
    ],
    "integration": [
        "Inspect the connector or webhook delivery logs for the affected workspace.",
        "Confirm the customer's authorization, scopes, and endpoint health.",
        "Replay or re-authorize only after the failing step is identified.",
    ],
    "other": [
        "Review the full transcript and retrieved documents.",
        "Confirm the customer's plan, workspace, and desired outcome.",
        "Respond within the plan's first-response target.",
    ],
}


def extract_attempted_steps(turns: list[Turn]) -> list[str]:
    """Pull customer-reported attempts such as 'I already cleared the cache'."""
    steps: list[str] = []
    for turn in turns:
        if turn.role != "user":
            continue
        for match in _ATTEMPT_RE.findall(turn.content):
            cleaned = " ".join(match.split()).strip(" ,.;")
            if cleaned and len(cleaned) > 8:
                steps.append(cleaned[0].upper() + cleaned[1:])
    return _dedupe(steps)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item.strip())
    return result


def _fallback_category(decision: EscalationDecision, persona: PersonaResult) -> str:
    for reason in decision.reasons:
        if reason.code.startswith("sensitive_"):
            category = reason.code.removeprefix("sensitive_")
            return _CATEGORY_BY_SENSITIVE.get(category, "other")
        if reason.code in {
            "low_retrieval_confidence",
            "insufficient_grounding",
            "ungrounded_response",
            "missing_citations",
            "retrieval_error",
        }:
            return "retrieval_gap"
    if persona.persona.value == "Technical Expert":
        return "technical"
    return "other"


def _issue_summary(session: Session, latest_message: str) -> str:
    user_turns = [turn.content.strip() for turn in session.history if turn.role == "user"]
    if not user_turns:
        return latest_message[:400]
    first = " ".join(user_turns[0].split())
    latest = " ".join(latest_message.split())
    if len(user_turns) == 1:
        return first[:400]
    return (
        f"Initial report: {first[:220]} "
        f"Latest update: {latest[:220]}"
    )


class HandoffBuilder:
    """Builds and persists the JSON/Markdown handoff for an escalation."""

    def __init__(self, llm: LLMClient | None) -> None:
        self.llm = llm

    def build(
        self,
        *,
        session: Session,
        persona_result: PersonaResult,
        decision: EscalationDecision,
        sources: list[RetrievedChunk],
        ticket_id: str,
        latest_message: str,
    ) -> Handoff:
        user_turns = [turn for turn in session.history if turn.role == "user"]
        attempted = _dedupe(
            session.attempted_steps
            + extract_attempted_steps(session.history)
        )[:12]
        issue = _issue_summary(session, latest_message)
        category = _fallback_category(decision, persona_result)
        severity = decision.severity
        recommendation = self._fallback_recommendation(category, decision)
        next_steps = list(_NEXT_STEPS.get(category, _NEXT_STEPS["other"]))

        if self.llm is not None:
            enrichment = self._enrich(
                session=session,
                persona_result=persona_result,
                decision=decision,
                sources=sources,
                attempted=attempted,
                fallback_issue=issue,
            )
            if enrichment:
                issue = enrichment.get("issue_summary", issue)[:800]
                category = enrichment.get("issue_category", category)
                severity = enrichment.get("severity", severity)
                recommendation = enrichment.get("recommendation", recommendation)[:600]
                llm_steps = enrichment.get("recommended_next_steps") or []
                if isinstance(llm_steps, list) and llm_steps:
                    next_steps = _dedupe(
                        [str(step)[:300] for step in llm_steps if str(step).strip()]
                    )[:5]

        documents_used = _dedupe([chunk.source for chunk in sources])
        retrieved_sources = [
            {
                "source": chunk.source,
                "title": chunk.title,
                "section": chunk.section,
                "page": chunk.page,
                "score": round(chunk.score, 4),
                "chunk_id": chunk.chunk_id,
            }
            for chunk in sources
        ]
        conversation = [
            {
                "role": turn.role,
                "content": turn.content,
                "persona": turn.persona,
                "timestamp": turn.timestamp,
            }
            for turn in session.history[-20:]
        ]
        if len(user_turns) > 20:
            conversation.insert(
                0,
                {
                    "role": "system",
                    "content": f"{len(user_turns) - 20} earlier turn(s) omitted from this summary.",
                    "persona": None,
                    "timestamp": iso(),
                },
            )

        return Handoff(
            ticket_id=ticket_id,
            session_id=session.session_id,
            created_at=iso(),
            persona=persona_result.persona.value,
            persona_confidence=persona_result.confidence,
            persona_reasoning=persona_result.reasoning,
            issue=issue,
            issue_category=category,
            documents_used=documents_used,
            retrieved_sources=retrieved_sources,
            attempted_steps=attempted,
            conversation_history=conversation,
            recommendation=recommendation,
            recommended_next_steps=next_steps,
            escalation_reasons=[reason.to_dict() for reason in decision.reasons],
            severity=severity,
            frustration_score=persona_result.frustration_score,
            turn_count=session.turn_count,
            latest_message=latest_message,
            wants_human=persona_result.wants_human,
        )

    def _fallback_recommendation(
        self, category: str, decision: EscalationDecision
    ) -> str:
        primary = decision.primary_reason
        if primary is None:
            return "Review the conversation and respond to the customer's request."
        return (
            f"{primary.label}. Review the transcript and retrieved sources, then "
            f"continue the case as a human owner ({category})."
        )

    def _enrich(
        self,
        *,
        session: Session,
        persona_result: PersonaResult,
        decision: EscalationDecision,
        sources: list[RetrievedChunk],
        attempted: list[str],
        fallback_issue: str,
    ) -> dict[str, Any] | None:
        context = "\n".join(
            f"- {chunk.title} | {chunk.section} | page {chunk.page or 'n/a'} "
            f"| score {chunk.score:.2f}"
            for chunk in sources
        ) or "(no documents retrieved)"
        reasons = "\n".join(
            f"- {reason.label} ({reason.code}): {reason.detail}" for reason in decision.reasons
        )
        steps = "\n".join(f"- {step}" for step in attempted) or "(none recorded)"
        prompt = (
            f"DETECTED PERSONA: {persona_result.persona.value} "
            f"(confidence {persona_result.confidence:.2f}, "
            f"frustration {persona_result.frustration_score:.2f})\n\n"
            f"CONVERSATION:\n{format_history(session.history, limit=12)}\n\n"
            f"ESCALATION REASONS:\n{reasons}\n\n"
            f"DOCUMENTS RETRIEVED:\n{context}\n\n"
            f"ATTEMPTED STEPS:\n{steps}\n\n"
            "Prepare the handoff."
        )
        try:
            data = self.llm.generate_json(
                prompt=prompt,
                system_instruction=HANDOFF_SYSTEM_INSTRUCTION,
                schema=HANDOFF_SCHEMA,
                temperature=0.2,
            )
        except LLMError as exc:
            LOGGER.warning("Handoff enrichment failed, using deterministic summary: %s", exc)
            return None

        allowed_categories = set(HANDOFF_SCHEMA["properties"]["issue_category"]["enum"])
        if data.get("issue_category") not in allowed_categories:
            data.pop("issue_category", None)
        if data.get("severity") not in {"high", "medium", "low"}:
            data.pop("severity", None)
        if not isinstance(data.get("issue_summary"), str) or not data["issue_summary"].strip():
            data.pop("issue_summary", None)
        return data


def save_handoff(handoff: Handoff, directory: Path) -> dict[str, str]:
    """Persist JSON and Markdown handoffs; returns their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"HANDOFF-{handoff.ticket_id}"
    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    json_path.write_text(handoff.to_json(), encoding="utf-8")
    md_path.write_text(handoff.to_markdown(), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
