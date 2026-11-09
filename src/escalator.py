"""Configurable escalation detection.

Two layers:

1. Deterministic sensitive-topic detection. Account-actionable billing, legal,
   and security requests must reach a human regardless of how good the retrieved
   answer looks, so these are matched with explicit patterns rather than left to
   sentiment or the LLM.
2. An escalation policy that combines retrieval confidence, grounding, customer
   sentiment, conversation length, and explicit human requests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .config import Settings
from .models import (
    EscalationDecision,
    EscalationReason,
    GenerationResult,
    Persona,
    PersonaResult,
)


@dataclass(frozen=True)
class SensitiveRule:
    category: str
    label: str
    severity: str
    team: str
    patterns: tuple[str, ...]
    informational_patterns: tuple[str, ...] = ()


SENSITIVE_RULES: tuple[SensitiveRule, ...] = (
    SensitiveRule(
        category="billing_dispute",
        label="Billing dispute or refund request",
        severity="high",
        team="Finance Operations",
        patterns=(
            r"\b(?:i|we)\s+(?:want|need|demand|request|expect|would\s+like)\s+(?:a\s+|an\s+)?"
            r"(?:\w+\s+){0,2}(?:refund|reimbursement|money\s+back|credit)\b",
            r"\b(?:give|issue|process|approve|send)\s+(?:me|us)\s+(?:a\s+)?"
            r"(?:\w+\s+){0,2}(?:refund|credit|compensation)\b",
            r"\bwhere(?:'s|\s+is)\s+my\s+refund\b",
            r"\brefund\s+(?:my|our|the)\s+(?:payment|charge|order|subscription|invoice)\b",
            r"\b(?:duplicate|double|twice|over)[- ]?(?:charges?|charged|billing)\b",
            r"\b(?:unexpected|unauthorized|unrecognized|incorrect|wrong|extra|fraudulent)\s+"
            r"(?:charges?|invoices?|bill(?:ing)?|fees?)\b",
            r"\b(?:dispute|contest|reject)\s+(?:the\s+|this\s+|my\s+|our\s+)?"
            r"(?:charges?|invoices?|bill|fees?|transactions?)\b",
            r"\b(?:waive|reverse)\s+(?:the\s+|this\s+|my\s+|our\s+)?(?:\w+\s+)?"
            r"(?:fees?|charges?|invoices?)\b",
            r"\bcharge\s?back\b",
        ),
        informational_patterns=(
            r"\b(?:billing|invoices?|refunds?|charges?|payments?|subscriptions?|"
            r"proration|tax(?:es)?)\b",
        ),
    ),
    SensitiveRule(
        category="legal",
        label="Legal or regulatory matter",
        severity="high",
        team="Legal",
        patterns=(
            r"\b(?:lawyer|attorney|legal\s+action|lawsuit|litigation|sue|suing|subpoena|court)\b",
            r"\b(?:regulator|regulatory|consumer\s+protection|ombudsman|legal\s+notice|"
            r"demand\s+letter|file\s+a\s+complaint)\b",
        ),
        informational_patterns=(r"\b(?:legal|terms|contract)\b",),
    ),
    SensitiveRule(
        category="account_security",
        label="Account-sensitive request",
        severity="high",
        team="Identity & Access",
        patterns=(
            r"\b(?:delete|remove|close|deactivate)\s+(?:my|our|the)\s+"
            r"(?:account|workspace|data)\b",
            r"\b(?:gdpr|ccpa)\s+(?:delete|deletion|erasure|request)\b",
            r"\b(?:transfer|change)\s+(?:of\s+)?(?:ownership|owner)\b",
            r"\b(?:change|update)\s+(?:my|our|the)\s+(?:account\s+)?email\b",
            r"\b(?:cancel|terminate)\s+(?:my|our|the)\s+(?:subscription|plan|account)\b",
        ),
        informational_patterns=(
            r"\b(?:account|ownership|delete|data\s+retention)\b",
        ),
    ),
    SensitiveRule(
        category="payment_change",
        label="Payment method change",
        severity="high",
        team="Finance Operations",
        patterns=(
            r"\b(?:update|change|remove|delete|replace|add)\s+(?:my|our|the)?\s*"
            r"(?:credit\s+card|card|payment\s+method|billing\s+method)\b",
        ),
    ),
    SensitiveRule(
        category="security_incident",
        label="Suspected account compromise or data breach",
        severity="high",
        team="Security Operations",
        patterns=(
            r"\b(?:hacked|compromised|account\s+takeover|data\s+breach)\b",
            r"\b(?:unauthorized|suspicious)\s+(?:access|login|activity)\b",
            r"\b(?:leaked|exposed)\s+(?:api\s+key|token|credentials?)\b",
            r"\bsomeone\s+(?:else\s+)?(?:logged|signed)\s+in\b",
        ),
    ),
)

_WANTS_HUMAN_RE = re.compile(
    r"\b(?:human|real\s+person|live\s+agent|human\s+agent|support\s+agent|"
    r"representative|supervisor|your\s+manager|a\s+manager|escalate(?:\s+this)?|"
    r"speak\s+(?:to|with)\s+(?:a|an|someone|somebody))\b",
    re.IGNORECASE,
)

_COMPILED = tuple(
    (
        rule,
        tuple(re.compile(pattern, re.IGNORECASE) for pattern in rule.patterns),
        tuple(
            re.compile(pattern, re.IGNORECASE)
            for pattern in rule.informational_patterns
        ),
    )
    for rule in SENSITIVE_RULES
)


@dataclass(frozen=True)
class SensitiveMatch:
    category: str
    label: str
    severity: str
    team: str
    matched_text: str
    escalated_because: str = "actionable_request"

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "label": self.label,
            "severity": self.severity,
            "team": self.team,
            "matched_text": self.matched_text,
            "escalated_because": self.escalated_because,
        }


class SensitiveTopicDetector:
    """Matches account-actionable sensitive requests.

    ``mode="always"`` also escalates informational mentions of billing, legal,
    or account topics. ``mode="actions_only"`` (default) answers policy questions
    from the KB but escalates concrete refund, dispute, deletion, transfer, and
    security requests.
    """

    def __init__(self, mode: str = "actions_only", extra_terms: Iterable[str] = ()) -> None:
        if mode not in {"actions_only", "always"}:
            raise ValueError("mode must be 'actions_only' or 'always'")
        self.mode = mode
        self.extra_terms = tuple(term.strip().lower() for term in extra_terms if term.strip())

    def detect(self, message: str) -> SensitiveMatch | None:
        for rule, actionable, informational in _COMPILED:
            for pattern in actionable:
                match = pattern.search(message)
                if match:
                    return SensitiveMatch(
                        category=rule.category,
                        label=rule.label,
                        severity=rule.severity,
                        team=rule.team,
                        matched_text=match.group(0),
                    )
            if self.mode == "always":
                for pattern in informational:
                    match = pattern.search(message)
                    if match:
                        return SensitiveMatch(
                            category=rule.category,
                            label=rule.label,
                            severity=rule.severity,
                            team=rule.team,
                            matched_text=match.group(0),
                            escalated_because="informational_mention_always_mode",
                        )

        lowered = message.lower()
        for term in self.extra_terms:
            if term in lowered:
                return SensitiveMatch(
                    category="custom",
                    label="Workspace-configured sensitive topic",
                    severity="medium",
                    team="Human support queue",
                    matched_text=term,
                    escalated_because="configured_term",
                )
        return None


def detect_human_request(message: str) -> bool:
    return bool(_WANTS_HUMAN_RE.search(message))


@dataclass(frozen=True)
class EscalationConfig:
    min_similarity: float = 0.52
    min_supporting_chunks: int = 1
    max_turns: int = 6
    frustration_streak_threshold: int = 2
    frustration_score_threshold: float = 0.6
    sensitive_mode: str = "actions_only"
    require_citations: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> "EscalationConfig":
        return cls(
            min_similarity=settings.min_retrieval_similarity,
            min_supporting_chunks=settings.min_supporting_chunks,
            max_turns=settings.max_turns_before_escalation,
            frustration_streak_threshold=settings.frustration_streak_threshold,
            frustration_score_threshold=settings.frustration_score_threshold,
            sensitive_mode=settings.sensitive_mode,
            require_citations=settings.require_citations,
        )


@dataclass
class EscalationContext:
    message: str
    persona: PersonaResult
    retrieval_top_score: float
    supporting_count: int
    generation: GenerationResult | None = None
    sensitive: SensitiveMatch | None = None
    wants_human: bool = False
    consecutive_negative: int = 0
    unresolved_turns: int = 0
    turn_count: int = 0


class EscalationPolicy:
    """Turns signals into an explainable escalation decision."""

    def __init__(self, config: EscalationConfig | None = None) -> None:
        self.config = config or EscalationConfig()

    def evaluate(self, context: EscalationContext) -> EscalationDecision:
        reasons: list[EscalationReason] = []
        sensitive_category = None

        if context.sensitive is not None:
            sensitive_category = context.sensitive.category
            reasons.append(
                EscalationReason(
                    code=f"sensitive_{context.sensitive.category}",
                    label=context.sensitive.label,
                    detail=(
                        f"Matched {context.sensitive.matched_text!r}; requires "
                        f"{context.sensitive.team} and cannot be resolved in chat."
                    ),
                    severity=context.sensitive.severity,
                )
            )

        if context.wants_human:
            reasons.append(
                EscalationReason(
                    code="human_requested",
                    label="Customer requested a human",
                    detail="The customer explicitly asked for a human or an escalation.",
                    severity="medium",
                )
            )

        if context.generation is None:
            if (
                context.retrieval_top_score < self.config.min_similarity
                or context.supporting_count < self.config.min_supporting_chunks
            ):
                reasons.append(
                    EscalationReason(
                        code="low_retrieval_confidence",
                        label="Low retrieval confidence",
                        detail=(
                            f"Top retrieval score {context.retrieval_top_score:.2f} "
                            f"(threshold {self.config.min_similarity:.2f}); "
                            f"{context.supporting_count} chunk(s) above threshold "
                            f"(required {self.config.min_supporting_chunks})."
                        ),
                        severity="high",
                    )
                )
        else:
            generation = context.generation
            if not generation.answerable:
                reasons.append(
                    EscalationReason(
                        code="insufficient_grounding",
                        label="No documented answer",
                        detail=(
                            generation.escalation_reason
                            or "The retrieved documentation does not answer the question."
                        ),
                        severity="high",
                    )
                )
            elif not generation.grounded:
                reasons.append(
                    EscalationReason(
                        code="ungrounded_response",
                        label="Answer failed the grounding check",
                        detail=(
                            generation.escalation_reason
                            or "The generated answer was not fully supported by the retrieved context."
                        ),
                        severity="high",
                    )
                )
            if generation.needs_escalation:
                reasons.append(
                    EscalationReason(
                        code="llm_recommended_escalation",
                        label="Agent recommended escalation",
                        detail=generation.escalation_reason
                        or "The response generator flagged the case for human review.",
                        severity="medium",
                    )
                )
            if (
                self.config.require_citations
                and not generation.citations
                and not re.search(r"\[S\d+\]", generation.answer or "")
            ):
                reasons.append(
                    EscalationReason(
                        code="missing_citations",
                        label="No verifiable citation",
                        detail="The answer did not cite any retrieved knowledge-base source.",
                        severity="medium",
                    )
                )

        if (
            context.consecutive_negative >= self.config.frustration_streak_threshold
            and context.persona.frustration_score >= self.config.frustration_score_threshold
        ):
            reasons.append(
                EscalationReason(
                    code="repeated_dissatisfaction",
                    label="Customer remains dissatisfied",
                    detail=(
                        f"{context.consecutive_negative} consecutive negative turns; "
                        f"frustration score {context.persona.frustration_score:.2f}."
                    ),
                    severity="high",
                )
            )

        if (
            context.unresolved_turns >= self.config.max_turns
            and (
                context.consecutive_negative >= 1
                or context.persona.frustration_score
                >= self.config.frustration_score_threshold
            )
        ):
            reasons.append(
                EscalationReason(
                    code="unresolved_conversation",
                    label="Unresolved after multiple turns",
                    detail=(
                        f"{context.unresolved_turns} unresolved turn(s), exceeding the "
                        f"configured limit of {self.config.max_turns}."
                    ),
                    severity="medium",
                )
            )

        deduped: list[EscalationReason] = []
        seen: set[str] = set()
        for reason in reasons:
            if reason.code not in seen:
                seen.add(reason.code)
                deduped.append(reason)

        return EscalationDecision(
            escalate=bool(deduped),
            reasons=deduped,
            sensitive_category=sensitive_category,
        )


def customer_friendly_reason(decision: EscalationDecision) -> str:
    """One short, non-technical sentence explaining the handoff to the customer."""
    if not decision.reasons:
        return "A specialist will review this case."
    reason = decision.reasons[0]
    mapping = {
        "sensitive_billing_dispute": "This involves account-specific billing, which must be handled by our billing team.",
        "sensitive_payment_change": "Payment method changes must go through our billing team.",
        "sensitive_legal": "This involves a legal matter that must be handled by our specialist team.",
        "sensitive_account_security": "This affects account security or ownership, so identity verification is required.",
        "sensitive_security_incident": "This may involve unauthorized access, so our security team needs to review it.",
        "sensitive_custom": "This requires a specialist from our human support team.",
        "low_retrieval_confidence": "I could not find documentation that confidently answers this.",
        "insufficient_grounding": "I do not have a documented answer I can stand behind.",
        "ungrounded_response": "I could not verify the answer against our documentation.",
        "missing_citations": "I could not verify the answer against our documentation.",
        "human_requested": "You asked to speak with a person.",
        "repeated_dissatisfaction": "We have tried several steps without resolving it.",
        "unresolved_conversation": "This has taken more back-and-forth than it should.",
        "llm_recommended_escalation": "This case needs human judgment.",
        "retrieval_error": "I could not search our documentation because of a system error.",
        "already_escalated": "This conversation is already with a human specialist.",
    }
    return mapping.get(reason.code, "A specialist is needed for this case.")


def persona_escalation_notice(
    persona: Persona,
    decision: EscalationDecision,
    ticket_id: str,
) -> str:
    """Persona-adapted escalation message that hands the case to a human."""
    reason = customer_friendly_reason(decision)
    team = "a human specialist"
    if decision.sensitive_category:
        for rule in SENSITIVE_RULES:
            if rule.category == decision.sensitive_category:
                team = f"our {rule.team} team"
                break

    if persona is Persona.FRUSTRATED:
        return (
            "I'm really sorry — I don't want to keep you going in circles. "
            f"{reason} I've passed this to {team} and created ticket **{ticket_id}**. "
            "You won't have to repeat yourself: they'll see our conversation, the "
            "documentation I checked, and the steps we've already tried. "
            "A person will follow up with you as soon as possible."
        )
    if persona is Persona.EXECUTIVE:
        return (
            f"I've routed this to {team} for direct handling. {reason} "
            f"Reference: **{ticket_id}**. The handoff summary includes the issue, "
            "business context, documents reviewed, and recommended next steps. "
            "The team will follow up within your plan's response target."
        )
    return (
        f"I'm escalating this to {team} with the diagnostic context from this session. "
        f"{reason} Ticket **{ticket_id}** has been created and includes the conversation, "
        "retrieved documentation, retrieval scores, and steps already attempted. "
        "A specialist will continue from here."
    )
