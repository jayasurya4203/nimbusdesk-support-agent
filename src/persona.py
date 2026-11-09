"""Customer persona detection and lightweight sentiment scoring.

Primary path: Gemini structured output. Fallback path: deterministic linguistic
rules so the agent keeps working (with lower confidence) if the model call
fails. A new classification only replaces the session persona when it is
reasonably confident, which prevents the badge and tone from flapping on every
short follow-up message.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Sequence

from .llm import LLMClient, LLMError
from .models import Persona, PersonaResult, Turn

LOGGER = logging.getLogger(__name__)

PERSONA_SCHEMA: dict = {
    "type": "OBJECT",
    "properties": {
        "persona": {"type": "STRING", "enum": Persona.values()},
        "confidence": {"type": "NUMBER"},
        "reasoning": {"type": "STRING"},
        "signals": {"type": "ARRAY", "items": {"type": "STRING"}},
        "frustration_score": {"type": "NUMBER"},
        "wants_human": {"type": "BOOLEAN"},
    },
    "required": [
        "persona",
        "confidence",
        "reasoning",
        "signals",
        "frustration_score",
        "wants_human",
    ],
}

CLASSIFIER_SYSTEM_INSTRUCTION = """You are a customer-persona classifier for NimbusDesk, a B2B SaaS support desk. Classify the customer's LATEST message into exactly one persona:

1. "Technical Expert" — uses engineering vocabulary, references APIs, logs, error codes, configuration, authentication, database, or infrastructure; wants precise technical detail.
2. "Frustrated User" — emotional or urgent language, complaints, exclamation marks, repeated attempts, phrases such as "nothing works" or "I've tried everything"; wants the problem fixed and to feel heard.
3. "Business Executive" — outcome-focused; references business impact, operations, revenue, SLA, downtime, timelines, risk, or resolution dates; prefers brevity.

Rules:
- Use prior conversation turns only as context; judge the latest customer message.
- Choose the dominant persona when signals are mixed.
- confidence is 0-1 and must reflect how clear the signals are.
- frustration_score is 0-1 based on emotional intensity, urgency, and repeated failed attempts.
- wants_human is true only when the customer explicitly asks for a human, agent, manager, supervisor, or escalation.
- Do not answer the support question. Do not invent facts.
- Return only the requested JSON object."""


_TECH_TERMS: dict[str, float] = {
    "api": 1.5, "endpoint": 1.5, "http": 1.0, "json": 1.0, "payload": 1.0,
    "header": 1.0, "bearer": 2.0, "token": 1.0, "oauth": 2.0, "jwt": 2.0,
    "saml": 2.0, "scim": 2.0, "sso": 1.5, "webhook": 2.0, "signature": 1.0,
    "hmac": 1.5, "curl": 1.5, "sdk": 1.0, "error code": 2.0, "log": 1.0,
    "logs": 1.5, "stack trace": 2.0, "traceback": 2.0, "401": 2.0, "403": 2.0,
    "404": 1.5, "429": 2.0, "500": 1.0, "502": 1.5, "503": 1.5, "config": 1.0,
    "configuration": 1.5, "parameter": 1.0, "parameters": 1.0, "schema": 1.0,
    "database": 1.0, "postgres": 2.0, "postgresql": 2.0, "mysql": 1.5,
    "snowflake": 1.5, "bigquery": 1.5, "redis": 1.0, "latency": 1.5,
    "rate limit": 2.0, "idempotency": 2.0, "idempotent": 2.0, "regex": 1.5,
    "kubernetes": 1.5, "docker": 1.0, "timeout": 1.0, "tls": 1.5, "ssl": 1.5,
    "certificate": 1.0, "dns": 1.5, "cidr": 1.5, "scope": 0.5, "scopes": 1.5,
    "refresh token": 2.0, "access token": 2.0, "root cause": 1.5,
    "steps to reproduce": 2.0, "reproduce": 1.0,
}

_EXEC_TERMS: dict[str, float] = {
    "business impact": 3.0, "impact on": 2.0, "operations": 2.0,
    "operational": 2.0, "downtime": 2.5, "outage": 2.0, "revenue": 2.0,
    "cost": 1.0, "costs": 1.0, "budget": 1.5, "roi": 2.0, "sla": 2.5,
    "uptime": 2.5, "timeline": 2.5, "eta": 2.0, "when will": 2.5,
    "resolution": 1.5, "resolved": 1.5, "executive": 2.0, "board": 2.0,
    "leadership": 2.0, "stakeholders": 2.0, "contract": 1.5, "renewal": 2.0,
    "compliance": 1.5, "risk": 1.0, "kpi": 2.0, "metrics": 1.0,
    "customer experience": 1.5, "enterprise": 1.0, "summary": 1.0,
}

_FRUSTRATED_PHRASES: dict[str, float] = {
    "nothing works": 3.0, "nothing is working": 3.0, "tried everything": 3.0,
    "still not working": 2.5, "still doesn't work": 2.5, "still not": 1.5,
    "doesn't work": 1.5, "not working": 1.5, "no one": 2.0, "third time": 2.5,
    "second time": 1.5, "again": 0.75, "frustrat": 2.5, "ridiculous": 2.5,
    "unacceptable": 2.5, "useless": 2.0, "waste of time": 2.5, "urgent": 1.5,
    "asap": 1.5, "immediately": 1.0, "angry": 2.0, "furious": 2.5,
    "fed up": 2.5, "terrible": 2.0, "worst": 2.0, "hate": 1.5,
    "how many times": 2.0, "why is this": 1.0, "help me": 0.5,
    "not helping": 2.0, "no response": 1.5, "waited": 1.0, "waited an hour": 2.0,
    "please fix": 1.0,
}

_WANTS_HUMAN_RE = re.compile(
    r"\b(?:human|real person|live agent|human agent|support agent|representative|"
    r"supervisor|your manager|a manager|escalate(?:\s+this)?|speak\s+(?:to|with)\s+"
    r"(?:a|an|someone|somebody))\b",
    re.IGNORECASE,
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def estimate_frustration(message: str) -> float:
    """Rule-based frustration score used alone or as an LLM sanity floor."""
    text = message.strip()
    if not text:
        return 0.0
    exclaims = min(text.count("!"), 4) / 4.0 * 0.45
    letters = [char for char in text if char.isalpha()]
    caps_ratio = (
        sum(1 for char in letters if char.isupper()) / len(letters) if letters else 0.0
    )
    caps = 0.2 if caps_ratio > 0.45 and len(letters) > 8 else 0.0
    phrase_score = 0.0
    for phrase, weight in _FRUSTRATED_PHRASES.items():
        if phrase in text.lower():
            phrase_score += weight * 0.22
    return round(_clamp(exclaims + caps + phrase_score), 3)


def wants_human(message: str) -> bool:
    return bool(_WANTS_HUMAN_RE.search(message))


def _argmax(scores: dict[Persona, float]) -> tuple[Persona, float, float]:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_persona, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    return top_persona, top_score, second_score


def rule_based_classify(message: str) -> PersonaResult:
    """Deterministic fallback classifier based on weighted lexical signals."""
    text = message.lower()
    scores = {persona: 0.0 for persona in Persona}

    for term, weight in _TECH_TERMS.items():
        if term in text:
            scores[Persona.TECHNICAL] += weight
    if "```" in message or re.search(r"\b[A-Za-z_]+_[A-Za-z_]+\b", message):
        scores[Persona.TECHNICAL] += 1.0
    if re.search(r"\b(?:GET|POST|PATCH|PUT|DELETE)\s+/", message):
        scores[Persona.TECHNICAL] += 2.0

    for term, weight in _EXEC_TERMS.items():
        if term in text:
            scores[Persona.EXECUTIVE] += weight

    for term, weight in _FRUSTRATED_PHRASES.items():
        if term in text:
            scores[Persona.FRUSTRATED] += weight
    scores[Persona.FRUSTRATED] += min(message.count("!"), 3) * 0.7
    letters = [char for char in message if char.isalpha()]
    if letters and sum(1 for char in letters if char.isupper()) / len(letters) > 0.55:
        scores[Persona.FRUSTRATED] += 1.5

    persona, top, second = _argmax(scores)
    if top == 0:
        return PersonaResult(
            persona=Persona.TECHNICAL,
            confidence=0.3,
            reasoning="No strong persona signals; defaulted to Technical Expert for a detailed answer.",
            signals=[],
            source="rules",
            frustration_score=estimate_frustration(message),
            wants_human=wants_human(message),
        )

    margin = (top - second) / max(top, 1e-9)
    confidence = round(_clamp(0.45 + 0.4 * margin, 0.45, 0.88), 3)
    signals = [
        term for term, weight in sorted(
            {**_TECH_TERMS, **_EXEC_TERMS, **_FRUSTRATED_PHRASES}.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if term in text
    ][:5]
    return PersonaResult(
        persona=persona,
        confidence=confidence,
        reasoning=f"Rule-based fallback: {persona.value} signals scored highest ({top:.1f}).",
        signals=signals,
        source="rules",
        frustration_score=estimate_frustration(message),
        wants_human=wants_human(message),
    )


def format_history(history: Sequence[Turn], limit: int = 6) -> str:
    if not history:
        return "(no prior turns)"
    lines = []
    for turn in history[-limit:]:
        content = " ".join(turn.content.split())
        if len(content) > 500:
            content = content[:500] + "…"
        lines.append(f"{turn.role.title()}: {content}")
    return "\n".join(lines)


class PersonaClassifier:
    """LLM-first persona classifier with rule fallback and hysteresis."""

    def __init__(self, llm: LLMClient | None, *, stickiness_threshold: float = 0.55) -> None:
        self.llm = llm
        self.stickiness_threshold = stickiness_threshold

    def classify(
        self,
        message: str,
        history: Sequence[Turn] | None = None,
        previous: Persona | None = None,
        forced: Persona | None = None,
    ) -> PersonaResult:
        if forced is not None:
            return PersonaResult(
                persona=forced,
                confidence=1.0,
                reasoning="Persona manually selected in the interface.",
                source="manual",
                frustration_score=estimate_frustration(message),
                wants_human=wants_human(message),
            )

        result = self._classify_with_llm(message, history or [])
        if result is None:
            result = rule_based_classify(message)

        # Persona hysteresis: avoid switching tone on a terse follow-up.
        if (
            previous is not None
            and previous != result.persona
            and result.source == "llm"
            and result.confidence < self.stickiness_threshold
        ):
            result = PersonaResult(
                persona=previous,
                confidence=result.confidence,
                reasoning=(
                    f"Kept the session persona ({previous.value}); the new signal was weak "
                    f"({result.confidence:.2f}). Model rationale: {result.reasoning}"
                ),
                signals=result.signals,
                source="session",
                frustration_score=result.frustration_score,
                wants_human=result.wants_human,
                latency_ms=result.latency_ms,
            )
        return result

    def _classify_with_llm(
        self, message: str, history: Sequence[Turn]
    ) -> PersonaResult | None:
        if self.llm is None:
            return None
        started = time.perf_counter()
        prompt = (
            f"PRIOR CONVERSATION:\n{format_history(history)}\n\n"
            f"LATEST CUSTOMER MESSAGE:\n{message}\n\n"
            "Classify the latest customer message."
        )
        try:
            data = self.llm.generate_json(
                prompt=prompt,
                system_instruction=CLASSIFIER_SYSTEM_INSTRUCTION,
                schema=PERSONA_SCHEMA,
                temperature=0.0,
            )
            persona = Persona.from_label(str(data.get("persona", "")))
            confidence = _clamp(float(data.get("confidence", 0.5)))
            frustration = _clamp(
                max(
                    float(data.get("frustration_score", 0.0)),
                    estimate_frustration(message) * 0.85,
                )
            )
            signals_raw = data.get("signals", [])
            signals = [str(signal)[:120] for signal in signals_raw][:6] if isinstance(
                signals_raw, list
            ) else []
            return PersonaResult(
                persona=persona,
                confidence=round(confidence, 3),
                reasoning=str(data.get("reasoning", ""))[:600],
                signals=signals,
                source="llm",
                frustration_score=round(frustration, 3),
                wants_human=bool(data.get("wants_human")) or wants_human(message),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except (LLMError, ValueError, TypeError, AttributeError) as exc:
            LOGGER.warning("Persona LLM classification failed, using rules: %s", exc)
            return None
