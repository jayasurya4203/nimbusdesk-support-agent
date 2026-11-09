"""End-to-end orchestration for one support conversation.

Flow: classify persona -> detect account-sensitive requests -> retrieve ->
pre-escalation check -> generate grounded answer -> post-escalation check ->
reply or human handoff. Every stage is timed so the UI can explain what
happened and why.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Callable

from .config import Settings
from .escalator import (
    EscalationConfig,
    EscalationContext,
    EscalationPolicy,
    SensitiveTopicDetector,
    detect_human_request,
    persona_escalation_notice,
)
from .generator import ResponseGenerator
from .handoff import HandoffBuilder, save_handoff
from .models import (
    AgentReply,
    EscalationDecision,
    EscalationReason,
    GenerationResult,
    Persona,
    PersonaResult,
    RetrievedChunk,
    Session,
    Turn,
    iso,
)
from .persona import PersonaClassifier
from .rag import KnowledgeBase

LOGGER = logging.getLogger(__name__)

_DISSATISFACTION_RE = re.compile(
    r"\b(?:still\s+(?:not|doesn't|isn't|no|broken)|not\s+working|doesn't\s+work|"
    r"didn't\s+work|no\s+luck|same\s+(?:issue|problem|error)|nothing\s+(?:works|changed)|"
    r"already\s+tried|tried\s+that\s+already|not\s+helping|no\s+change|"
    r"still\s+happening|keeps?\s+happening)\b",
    re.IGNORECASE,
)

_RESOLUTION_RE = re.compile(
    r"\b(?:thanks|thank\s+you|that\s+(?:worked|fixed|solved)|it\s+works(?:\s+now)?|"
    r"fixed\s+it|solved|resolved|all\s+good|no\s+further\s+questions|"
    r"we'?re\s+good|that\s+did\s+it)\b",
    re.IGNORECASE,
)


def new_ticket_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"HD-{stamp}-{secrets.token_hex(3).upper()}"


class SupportAgent:
    def __init__(
        self,
        *,
        settings: Settings,
        knowledge_base: KnowledgeBase,
        classifier: PersonaClassifier,
        generator: ResponseGenerator,
        policy: EscalationPolicy,
        handoff_builder: HandoffBuilder,
        sensitive_detector: SensitiveTopicDetector,
    ) -> None:
        self.settings = settings
        self.kb = knowledge_base
        self.classifier = classifier
        self.generator = generator
        self.policy = policy
        self.handoff_builder = handoff_builder
        self.sensitive_detector = sensitive_detector

    # --------------------------------------------------------------- factories
    @classmethod
    def production(
        cls,
        settings: Settings,
        *,
        build_index_if_missing: bool = True,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> "SupportAgent":
        from .embeddings import GeminiEmbedder
        from .llm import GeminiLLM

        api_key = settings.require_api_key()
        llm = GeminiLLM(
            api_key=api_key,
            model=settings.chat_model,
            max_retries=settings.max_retries,
            base_delay_s=settings.retry_base_delay_s,
        )
        embedder = GeminiEmbedder(
            api_key=api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
            max_retries=settings.max_retries,
            base_delay_s=settings.retry_base_delay_s,
            inputs_per_minute=settings.embedding_inputs_per_minute,
        )
        knowledge_base = KnowledgeBase(settings, embedder)
        if not knowledge_base.exists():
            if not build_index_if_missing:
                raise FileNotFoundError(
                    "Knowledge base index is missing. Run `python scripts/ingest.py`."
                )
            knowledge_base.build(progress=progress)
        else:
            knowledge_base.load()

        return cls(
            settings=settings,
            knowledge_base=knowledge_base,
            classifier=PersonaClassifier(llm),
            generator=ResponseGenerator(llm),
            policy=EscalationPolicy(EscalationConfig.from_settings(settings)),
            handoff_builder=HandoffBuilder(llm),
            sensitive_detector=SensitiveTopicDetector(
                mode=settings.sensitive_mode,
                extra_terms=settings.extra_sensitive_terms,
            ),
        )

    def new_session(self) -> Session:
        return Session(session_id=f"S-{secrets.token_hex(4).upper()}")

    # ------------------------------------------------------------------- turns
    def respond(
        self,
        session: Session,
        message: str,
        forced_persona: Persona | None = None,
    ) -> AgentReply:
        message = message.strip()
        if not message:
            raise ValueError("message cannot be empty")

        started = time.perf_counter()
        timings: dict[str, int] = {}

        if session.escalated:
            return self._respond_after_escalation(session, message, forced_persona)

        classify_started = time.perf_counter()
        persona_result = self.classifier.classify(
            message,
            session.recent_history(),
            previous=session.persona,
            forced=forced_persona,
        )
        timings["classify_ms"] = int((time.perf_counter() - classify_started) * 1000)

        negative = self._is_negative(message, persona_result)
        positive = self._is_resolution(message) and not negative
        if positive:
            session.frustration_streak = 0
            session.unresolved_turns = 0
            session.resolved = True
        elif negative:
            session.frustration_streak += 1
            session.unresolved_turns += 1
            session.resolved = False

        session.persona = persona_result.persona
        session.persona_result = persona_result
        session.add_turn(
            Turn(
                role="user",
                content=message,
                persona=persona_result.persona.value,
                meta={
                    "persona_confidence": persona_result.confidence,
                    "frustration_score": persona_result.frustration_score,
                    "persona_source": persona_result.source,
                },
            )
        )

        sensitive = self.sensitive_detector.detect(message)
        chat_wants_human = detect_human_request(message) or persona_result.wants_human

        retrieval_started = time.perf_counter()
        try:
            sources = self.kb.retrieve(message, top_k=self.settings.top_k)
            supporting = self.kb.supporting_chunks(sources)
        except Exception as exc:  # noqa: BLE001 - retrieval outage must not break chat
            LOGGER.exception("Retrieval failed: %s", exc)
            decision = EscalationDecision(
                escalate=True,
                reasons=[
                    EscalationReason(
                        code="retrieval_error",
                        label="Documentation search failed",
                        detail="The knowledge base could not be searched during this turn.",
                        severity="high",
                    )
                ],
            )
            timings["retrieval_ms"] = int((time.perf_counter() - retrieval_started) * 1000)
            timings["total_ms"] = int((time.perf_counter() - started) * 1000)
            return self._escalate(
                session=session,
                persona_result=persona_result,
                decision=decision,
                sources=[],
                message=message,
                generation=None,
                timings=timings,
            )
        timings["retrieval_ms"] = int((time.perf_counter() - retrieval_started) * 1000)

        top_score = sources[0].score if sources else 0.0
        session.last_retrieval_score = top_score
        base_context = {
            "message": message,
            "persona": persona_result,
            "retrieval_top_score": top_score,
            "supporting_count": len(supporting),
            "sensitive": sensitive,
            "wants_human": chat_wants_human,
            "consecutive_negative": session.frustration_streak,
            "unresolved_turns": session.unresolved_turns,
            "turn_count": session.turn_count + 1,
        }

        decision = self.policy.evaluate(
            EscalationContext(**base_context, generation=None)
        )
        generation: GenerationResult | None = None

        if not decision.escalate:
            generation_started = time.perf_counter()
            generation = self.generator.generate(
                query=message,
                persona_result=persona_result,
                chunks=supporting,
                history=session.history[:-1],
            )
            timings["generate_ms"] = int((time.perf_counter() - generation_started) * 1000)
            decision = self.policy.evaluate(
                EscalationContext(**base_context, generation=generation)
            )

        if decision.escalate:
            timings["total_ms"] = int((time.perf_counter() - started) * 1000)
            return self._escalate(
                session=session,
                persona_result=persona_result,
                decision=decision,
                sources=sources,
                message=message,
                generation=generation,
                timings=timings,
            )

        assert generation is not None
        answer = generation.answer.strip()
        cited = [citation["source"] for citation in generation.citations]
        session.add_turn(
            Turn(
                role="assistant",
                content=answer,
                persona=persona_result.persona.value,
                meta={
                    "sources": cited,
                    "escalated": False,
                    "confidence": generation.confidence,
                },
            )
        )
        session.remember_steps(generation.steps)
        session.remember_sources(cited or [chunk.source for chunk in sources])
        session.turn_count += 1
        timings["total_ms"] = int((time.perf_counter() - started) * 1000)

        response_confidence = round(
            0.45 * top_score + 0.55 * generation.confidence, 4
        )
        return AgentReply(
            message=answer,
            session_id=session.session_id,
            persona=persona_result,
            sources=sources,
            escalation=decision,
            generation=generation,
            retrieval_confidence=round(top_score, 4),
            response_confidence=response_confidence,
            timings_ms=timings,
            forced_persona=persona_result.source == "manual",
        )

    # --------------------------------------------------------------- internals
    def _escalate(
        self,
        *,
        session: Session,
        persona_result: PersonaResult,
        decision: EscalationDecision,
        sources: list[RetrievedChunk],
        message: str,
        generation: GenerationResult | None,
        timings: dict[str, int],
    ) -> AgentReply:
        handoff_started = time.perf_counter()
        ticket_id = new_ticket_id()
        handoff = self.handoff_builder.build(
            session=session,
            persona_result=persona_result,
            decision=decision,
            sources=sources,
            ticket_id=ticket_id,
            latest_message=message,
        )
        paths = save_handoff(handoff, self.settings.handoff_dir)
        timings["handoff_ms"] = int((time.perf_counter() - handoff_started) * 1000)

        notice = persona_escalation_notice(
            persona_result.persona, decision, ticket_id
        )
        session.add_turn(
            Turn(
                role="assistant",
                content=notice,
                persona=persona_result.persona.value,
                meta={
                    "escalated": True,
                    "ticket_id": ticket_id,
                    "reasons": decision.reason_codes,
                },
            )
        )
        session.remember_steps(generation.steps if generation else [])
        session.remember_sources([chunk.source for chunk in sources])
        session.turn_count += 1
        session.escalated = True
        session.escalated_at = iso()
        session.handoff = handoff.to_dict()
        session.handoff_paths = paths

        LOGGER.info(
            "Escalated session %s as %s (reasons: %s)",
            session.session_id,
            ticket_id,
            ", ".join(decision.reason_codes) or "unspecified",
        )
        return AgentReply(
            message=notice,
            session_id=session.session_id,
            persona=persona_result,
            sources=sources,
            escalation=decision,
            handoff=handoff.to_dict(),
            handoff_paths=paths,
            generation=generation,
            retrieval_confidence=round(
                sources[0].score if sources else 0.0, 4
            ),
            response_confidence=0.0,
            timings_ms=timings,
            forced_persona=persona_result.source == "manual",
        )

    def _respond_after_escalation(
        self,
        session: Session,
        message: str,
        forced_persona: Persona | None = None,
    ) -> AgentReply:
        # The ticket owns the answer now, but the badge should still describe
        # the message the customer just sent rather than the escalated turn.
        persona_result = self.classifier.classify(
            message,
            session.recent_history(),
            previous=session.persona,
            forced=forced_persona,
        )
        session.persona = persona_result.persona
        session.persona_result = persona_result
        session.add_turn(
            Turn(
                role="user",
                content=message,
                persona=persona_result.persona.value,
                meta={"after_escalation": True},
            )
        )
        session.turn_count += 1
        ticket_id = (session.handoff or {}).get("ticket_id", "the human queue")

        if persona_result.persona is Persona.FRUSTRATED:
            notice = (
                f"I haven't forgotten you. Ticket **{ticket_id}** is already with a human "
                "specialist, and this conversation stays linked to it. Anything you add here "
                "will be available to them when they pick it up."
            )
        elif persona_result.persona is Persona.EXECUTIVE:
            notice = (
                f"Ticket **{ticket_id}** is already assigned to a specialist. The handoff "
                "includes the full context and recommended next steps. They will follow up "
                "within your plan's response target."
            )
        else:
            notice = (
                f"Ticket **{ticket_id}** is already with a human specialist. Additional "
                "details you share here remain linked to the ticket for their review."
            )
        session.add_turn(
            Turn(
                role="assistant",
                content=notice,
                persona=persona_result.persona.value,
                meta={"escalated": True, "ticket_id": ticket_id},
            )
        )
        decision = EscalationDecision(
            escalate=True,
            reasons=[
                EscalationReason(
                    code="already_escalated",
                    label="Conversation already assigned to a human",
                    detail=f"Ticket {ticket_id} is open with a human specialist.",
                    severity="medium",
                )
            ],
        )
        return AgentReply(
            message=notice,
            session_id=session.session_id,
            persona=persona_result,
            escalation=decision,
            handoff=session.handoff,
            handoff_paths=session.handoff_paths,
            retrieval_confidence=0.0,
            response_confidence=0.0,
            forced_persona=persona_result.source == "manual",
        )

    def _is_negative(self, message: str, persona_result: PersonaResult) -> bool:
        return (
            persona_result.frustration_score
            >= self.settings.frustration_score_threshold
            or bool(_DISSATISFACTION_RE.search(message))
        )

    def _is_resolution(self, message: str) -> bool:
        return bool(_RESOLUTION_RE.search(message))
