"""Streamlit chat interface for the persona-adaptive support agent."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent import SupportAgent  # noqa: E402
from src.config import Settings  # noqa: E402
from src.feedback import record_feedback  # noqa: E402
from src.models import AgentReply, Persona  # noqa: E402

LOGGER = logging.getLogger(__name__)

st.set_page_config(
    page_title="NimbusDesk · Persona-Adaptive Support",
    page_icon="🎧",
    layout="centered",
    initial_sidebar_state="expanded",
)

PERSONA_STYLES = {
    Persona.TECHNICAL: ("persona-tech", "🛠️"),
    Persona.FRUSTRATED: ("persona-frustrated", "💬"),
    Persona.EXECUTIVE: ("persona-exec", "📊"),
}

EXAMPLES = [
    (
        "Frustrated · browser",
        "Where is the guide to clear cookies? It's been an hour and nothing is loading on your interface!",
    ),
    (
        "Technical · auth",
        "What are the header parameter requirements for your bearer token auth implementation?",
    ),
    (
        "Executive · SLA",
        "Our operational uptime is decreasing. What uptime commitment do we have and who "
        "should we contact during an incident?",
    ),
    (
        "Escalate · billing",
        "My billing statement has unexpected duplicate charges. I demand an immediate refund!",
    ),
    (
        "Escalate · unknown",
        "Can you ship a physical welcome kit to our Antarctic research station, and what import tax applies?",
    ),
]

CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', system-ui, sans-serif; }
  .block-container { padding-top: 2.2rem; padding-bottom: 6rem; max-width: 880px; }
  .hero {
    background: linear-gradient(135deg, #0b2545 0%, #123b5c 55%, #0f766e 100%);
    border-radius: 18px; padding: 26px 28px; color: #f8fafc;
    box-shadow: 0 18px 40px -24px rgba(11, 37, 69, 0.8); margin-bottom: 18px;
  }
  .hero h1 { font-size: 1.55rem; margin: 0 0 6px 0; letter-spacing: -0.02em; }
  .hero p { margin: 0; color: #cbd5e1; font-size: 0.92rem; line-height: 1.5; }
  .hero .chips { margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap; }
  .chip {
    background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.18);
    padding: 4px 10px; border-radius: 999px; font-size: 0.72rem; letter-spacing: 0.04em;
    text-transform: uppercase; color: #e2e8f0;
  }
  .persona-badge {
    display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px;
    border-radius: 999px; font-size: 0.76rem; font-weight: 600; letter-spacing: 0.01em;
  }
  .persona-tech { background: #e0f2fe; color: #075985; }
  .persona-frustrated { background: #ffedd5; color: #9a3412; }
  .persona-exec { background: #ede9fe; color: #5b21b6; }
  .meta-pill {
    display: inline-block; padding: 3px 9px; border-radius: 999px;
    background: #f1f5f9; color: #475569; font-size: 0.72rem; margin-right: 6px;
    border: 1px solid #e2e8f0;
  }
  .meta-pill.warn { background: #fef2f2; color: #b91c1c; border-color: #fecaca; }
  .meta-pill.ok { background: #ecfdf5; color: #047857; border-color: #a7f3d0; }
  .meta-row { margin: 8px 0 10px 0; }
  .section-label {
    text-transform: uppercase; letter-spacing: 0.09em; font-size: 0.68rem;
    color: #64748b; font-weight: 600; margin: 14px 0 6px 0;
  }
  .source-card {
    border-left: 3px solid #0f766e; background: #f8fafc; padding: 8px 12px;
    border-radius: 6px; margin-bottom: 8px; font-size: 0.84rem;
  }
  .source-card .loc { color: #64748b; font-size: 0.76rem; }
  .escalation-box {
    border: 1px solid #fecaca; background: #fef2f2; border-radius: 10px;
    padding: 12px 16px; margin: 10px 0;
  }
  .escalation-box strong { color: #991b1b; }
  .escalation-box ul { margin: 6px 0 0 18px; }
  .stChatMessage { border-radius: 12px; }
  section[data-testid="stSidebar"] .block-container { padding-top: 1.4rem; }
  #MainMenu, footer { visibility: hidden; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def load_streamlit_secrets() -> None:
    """Copy Gemini settings from Streamlit secrets into env for cloud deploys."""
    keys = (
        "GEMINI_API_KEY",
        "CHAT_MODEL",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSIONS",
        "TOP_K",
        "MIN_RETRIEVAL_SIMILARITY",
    )
    try:
        secrets = st.secrets
    except Exception:  # noqa: BLE001 - no secrets.toml locally
        return
    for key in keys:
        if not os.getenv(key):
            try:
                value = secrets[key]
            except Exception:  # noqa: BLE001 - key not present
                continue
            os.environ[key] = str(value)


@st.cache_resource(show_spinner=False)
def get_agent(top_k: int, min_similarity: float, cache_bust: int) -> SupportAgent:
    del cache_bust
    settings = Settings.load().with_overrides(
        top_k=top_k, min_retrieval_similarity=min_similarity
    )
    settings.require_api_key()
    return SupportAgent.production(settings, build_index_if_missing=False)


def build_index(settings: Settings, top_k: int, min_similarity: float) -> dict:
    from src.embeddings import GeminiEmbedder
    from src.rag import KnowledgeBase

    overridden = settings.with_overrides(
        top_k=top_k, min_retrieval_similarity=min_similarity
    )
    embedder = GeminiEmbedder(
        api_key=overridden.require_api_key(),
        model=overridden.embedding_model,
        dimensions=overridden.embedding_dimensions,
        batch_size=overridden.embedding_batch_size,
        max_retries=overridden.max_retries,
        base_delay_s=overridden.retry_base_delay_s,
        inputs_per_minute=overridden.embedding_inputs_per_minute,
    )
    kb = KnowledgeBase(overridden, embedder)
    progress = st.progress(0.0, text="Parsing documents…")

    def callback(done: int, total: int, label: str) -> None:
        progress.progress(min(done / total, 1.0), text=label)

    stats = kb.build(progress=callback)
    progress.progress(1.0, text=f"Indexed {stats['chunk_count']} chunks")
    return stats


def _already_escalated(reply: AgentReply) -> bool:
    return any(
        reason.code == "already_escalated" for reason in reply.escalation.reasons
    )


def render_badges(reply: AgentReply) -> None:
    persona = reply.persona
    class_name, icon = PERSONA_STYLES.get(persona.persona, ("persona-tech", "🎧"))
    if _already_escalated(reply):
        status = '<span class="meta-pill warn">with human</span>'
        scores = '<span class="meta-pill">retrieval not re-run</span>'
    else:
        status = (
            '<span class="meta-pill warn">escalated</span>'
            if reply.escalation.escalate
            else '<span class="meta-pill ok">grounded answer</span>'
        )
        scores = (
            f'<span class="meta-pill">retrieval {reply.retrieval_confidence:.2f}</span>'
            f'<span class="meta-pill">response {reply.response_confidence:.2f}</span>'
        )
    source = "manual" if reply.persona.source == "manual" else persona.source
    st.markdown(
        '<div class="meta-row">'
        f'<span class="persona-badge {class_name}">{icon} {persona.persona.value}</span> '
        f'<span class="meta-pill">{persona.confidence:.0%} · {source}</span>'
        f'<span class="meta-pill">frustration {persona.frustration_score:.2f}</span>'
        f"{scores}{status}</div>",
        unsafe_allow_html=True,
    )


def render_sources(reply: AgentReply) -> None:
    if not reply.sources:
        if _already_escalated(reply):
            st.caption(
                "Retrieval is not re-run after a handoff; the ticket keeps the sources "
                "from the escalated turn."
            )
        else:
            st.caption("No knowledge-base chunks were retrieved.")
        return
    with st.expander(f"Retrieved sources · top {len(reply.sources)}", expanded=False):
        for index, chunk in enumerate(reply.sources, start=1):
            location = f"page {chunk.page}" if chunk.page else chunk.section
            st.markdown(
                f'<div class="source-card"><strong>S{index} · {chunk.title}</strong> '
                f'<span class="loc">— {chunk.source} · {location}</span><br>'
                f'<span class="loc">fused {chunk.score:.3f} · dense '
                f'{chunk.dense_score:.3f} · lexical {chunk.lexical_score:.3f}</span>'
                f"<br>{chunk.text[:520].strip()}…</div>",
                unsafe_allow_html=True,
            )


def render_generation(reply: AgentReply) -> None:
    generation = reply.generation
    if generation is None:
        return
    with st.expander("Generation details", expanded=False):
        left, middle, right = st.columns(3)
        left.metric("Model confidence", f"{generation.confidence:.0%}")
        middle.metric("Grounded", "yes" if generation.grounded else "no")
        right.metric("Answerable", "yes" if generation.answerable else "no")
        if generation.citations:
            st.markdown("**Citations**")
            for citation in generation.citations:
                st.markdown(
                    f"- `{citation.get('source')}` · {citation.get('section')} "
                    f"· {citation.get('page', '—')}"
                )
        if generation.steps:
            st.markdown("**Steps included in the answer**")
            for step in generation.steps:
                st.markdown(f"- {step}")
        if generation.escalation_reason:
            st.caption(f"Escalation rationale: {generation.escalation_reason}")
        if reply.timings_ms:
            st.caption(
                " · ".join(
                    f"{key.removesuffix('_ms')} {value} ms"
                    for key, value in reply.timings_ms.items()
                )
            )


def render_escalation(reply: AgentReply, index: int) -> None:
    if not reply.escalation.escalate:
        return
    ticket_id = (reply.handoff or {}).get("ticket_id", "pending")
    severity = reply.escalation.severity
    reasons = "".join(
        f"<li><strong>{reason.label}</strong> — {reason.detail}</li>"
        for reason in reply.escalation.reasons
    )
    st.markdown(
        f'<div class="escalation-box"><strong>Human handoff created · '
        f"{ticket_id}</strong> · severity {severity}"
        f"<ul>{reasons}</ul></div>",
        unsafe_allow_html=True,
    )
    if reply.handoff:
        with st.expander("Human handoff summary", expanded=True):
            st.json(reply.handoff, expanded=False)
            json_text = json.dumps(reply.handoff, indent=2, ensure_ascii=False)
            markdown_text = ""
            paths = reply.handoff_paths or {}
            if paths.get("markdown"):
                try:
                    markdown_text = Path(paths["markdown"]).read_text(encoding="utf-8")
                except OSError:
                    markdown_text = ""
            col_json, col_md = st.columns(2)
            col_json.download_button(
                "Download JSON",
                data=json_text,
                file_name=f"HANDOFF-{ticket_id}.json",
                mime="application/json",
                key=f"dl-json-{index}-{ticket_id}",
                use_container_width=True,
            )
            col_md.download_button(
                "Download ticket (MD)",
                data=markdown_text or reply.message,
                file_name=f"HANDOFF-{ticket_id}.md",
                mime="text/markdown",
                key=f"dl-md-{index}-{ticket_id}",
                use_container_width=True,
            )


def render_feedback(entry: dict, index: int, settings: Settings) -> None:
    reply: AgentReply = entry["reply"]
    recorded = entry.get("feedback")
    if recorded:
        st.caption(f"Feedback recorded: {recorded}")
        return
    up_col, down_col, _ = st.columns([1, 1, 5])
    if up_col.button("👍 Helpful", key=f"up-{index}"):
        entry["feedback"] = "👍 Helpful"
        record_feedback(
            settings.feedback_file,
            session_id=reply.session_id,
            persona=reply.persona.persona.value,
            rating="up",
            message=entry["user"],
            response_excerpt=reply.message,
            sources=[chunk.source for chunk in reply.sources],
            escalated=reply.escalation.escalate,
        )
        st.toast("Thanks — feedback saved.")
        st.rerun()
    if down_col.button("👎 Not helpful", key=f"down-{index}"):
        entry["show_comment"] = True
        st.rerun()
    if entry.get("show_comment"):
        with st.form(key=f"comment-form-{index}"):
            comment = st.text_input("What went wrong? (optional)")
            submitted = st.form_submit_button("Send feedback")
            if submitted:
                entry["feedback"] = "👎 Not helpful"
                entry["show_comment"] = False
                record_feedback(
                    settings.feedback_file,
                    session_id=reply.session_id,
                    persona=reply.persona.persona.value,
                    rating="down",
                    message=entry["user"],
                    response_excerpt=reply.message,
                    sources=[chunk.source for chunk in reply.sources],
                    comment=comment,
                    escalated=reply.escalation.escalate,
                )
                st.toast("Feedback saved.")
                st.rerun()


def render_sidebar_controls(
    settings: Settings,
    top_k: int,
    min_similarity: float,
    debug: bool,
) -> tuple[str, int, float, bool]:
    with st.sidebar:
        st.markdown("### 🎧 NimbusDesk Support")
        st.caption("Persona-adaptive agent · Gemini + RAG + human handoff")

        if settings.has_api_key:
            st.success("Gemini API key loaded", icon="✅")
        else:
            st.error("GEMINI_API_KEY missing", icon="🔑")

        st.markdown("#### Conversation")
        persona_mode = st.selectbox(
            "Persona mode",
            [
                "Auto-detect",
                Persona.TECHNICAL.value,
                Persona.FRUSTRATED.value,
                Persona.EXECUTIVE.value,
            ],
            help="Auto-detect classifies every message. Forcing a persona is useful for demos.",
        )
        top_k = st.slider("Top-k chunks", 2, 6, top_k)
        min_similarity = st.slider(
            "Escalation threshold (min similarity)",
            min_value=0.30,
            max_value=0.80,
            value=min_similarity,
            step=0.01,
            help="If the best fused retrieval score is below this value, the agent escalates.",
        )
        debug = st.toggle("Show generation details", value=debug)

        reset = st.button("🔄 New conversation", use_container_width=True)

        st.markdown("#### Example queries")
        for label, query in EXAMPLES:
            if st.button(label, key=f"example-{label}", use_container_width=True):
                st.session_state["pending_query"] = query
                st.rerun()

        with st.expander("How it works"):
            st.markdown(
                "1. **Persona detection** — Gemini structured output, with a rule-based fallback.\n"
                "2. **Hybrid retrieval** — Gemini embeddings + Chroma cosine search, re-ranked with BM25.\n"
                "3. **Adaptive grounded generation** — persona-specific prompt, citations required.\n"
                "4. **Escalation checks** — confidence, grounding, sensitive topics, frustration.\n"
                "5. **Human handoff** — structured JSON + Markdown ticket saved to `handoffs/`."
            )
    return persona_mode, top_k, min_similarity, reset


def render_sidebar_kb(
    settings: Settings,
    agent: SupportAgent,
    top_k: int,
    min_similarity: float,
) -> None:
    with st.sidebar:
        stats = agent.kb.stats()
        st.markdown("#### Knowledge base")
        col_a, col_b = st.columns(2)
        col_a.metric("Documents", stats["document_count"])
        col_b.metric("Chunks", stats["chunk_count"])
        st.caption(
            f"`{stats['embedding_model']}` · {stats['embedding_dimensions']} dims · "
            f"{stats['chunk_size']}/{stats['chunk_overlap']} chunking"
        )
        if stats.get("built_at"):
            st.caption(f"Indexed {stats['built_at']}")
        stale = agent.kb.staleness_reason()
        if stale:
            st.warning(f"Index needs rebuild: {stale}")
        if st.button("♻️ Rebuild index", use_container_width=True):
            with st.spinner("Rebuilding embeddings…"):
                build_index(settings, top_k, min_similarity)
            st.cache_resource.clear()
            st.session_state["cache_bust"] = st.session_state.get("cache_bust", 0) + 1
            st.success("Index rebuilt.")
            st.rerun()

        st.markdown("#### Escalation policy")
        st.caption(
            f"• Top score < **{min_similarity:.2f}** or no supporting chunk\n"
            "• Billing, legal, account-action, or security request\n"
            "• Customer asks for a human\n"
            "• Unsupported or uncited answer\n"
            f"• ≥ **2** consecutive negative turns\n"
            f"• > **{settings.max_turns_before_escalation}** unresolved turns"
        )
        st.caption(f"Sensitive mode: `{settings.sensitive_mode}`")

        if st.session_state.get("messages"):
            st.markdown("#### Session analytics")
            replies = [entry["reply"] for entry in st.session_state["messages"]]
            counts: dict[str, int] = {}
            for reply in replies:
                label = reply.persona.persona.value
                counts[label] = counts.get(label, 0) + 1
            if counts:
                st.bar_chart(counts)
            searched = [r for r in replies if not _already_escalated(r)]
            st.caption(
                f"{len(replies)} turn(s) · "
                f"{sum(1 for r in replies if r.escalation.escalate)} escalation(s) · "
                f"avg retrieval "
                f"{sum(r.retrieval_confidence for r in searched) / max(len(searched), 1):.2f}"
            )


def main() -> None:
    inject_css()
    load_streamlit_secrets()
    logging.basicConfig(level=logging.WARNING)

    settings = Settings.load()
    top_k = int(os.getenv("TOP_K", settings.top_k))
    min_similarity = settings.min_retrieval_similarity
    debug = True

    persona_mode, top_k, min_similarity, reset = render_sidebar_controls(
        settings, top_k, min_similarity, debug
    )

    st.markdown(
        '<div class="hero"><h1>NimbusDesk · Persona-Adaptive Support Agent</h1>'
        "<p>Detects who is writing — technical expert, frustrated user, or business executive — "
        "retrieves the right policy or troubleshooting passage, adapts the answer, and hands "
        "off to a human with a complete summary when the case leaves safe ground.</p>"
        '<div class="chips"><span class="chip">Persona-aware</span>'
        '<span class="chip">Grounded in 19 docs</span><span class="chip">Hybrid RAG</span>'
        '<span class="chip">Human-in-the-loop</span></div></div>',
        unsafe_allow_html=True,
    )

    if not settings.has_api_key:
        st.error(
            "**GEMINI_API_KEY is not configured.** Add it to `.env` (local) or "
            "Streamlit secrets (cloud), then reload."
        )
        st.code(
            "cp .env.example .env\n# edit .env and set GEMINI_API_KEY=...\n"
            "python scripts/ingest.py",
            language="bash",
        )
        st.stop()

    cache_bust = st.session_state.get("cache_bust", 0)
    agent: SupportAgent | None = None
    try:
        with st.spinner("Loading agent and vector index…"):
            agent = get_agent(top_k, min_similarity, cache_bust)
    except FileNotFoundError:
        agent = None
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Failed to load agent")
        st.error(f"Could not load the agent: {exc}")
        st.stop()

    if agent is None:
        st.warning(
            "The vector index has not been built yet. Build it once; it is reused on "
            "subsequent runs."
        )
        st.code("python scripts/ingest.py", language="bash")
        if st.button("Build knowledge base now", type="primary"):
            try:
                stats = build_index(settings, top_k, min_similarity)
                st.cache_resource.clear()
                st.session_state["cache_bust"] = cache_bust + 1
                st.success(
                    f"Indexed {stats['chunk_count']} chunks from "
                    f"{stats['document_count']} documents."
                )
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Index build failed")
                st.error(f"Index build failed: {exc}")
        st.stop()

    # Sidebar KB stats require a loaded agent, so they render after it is available.
    render_sidebar_kb(settings, agent, top_k, min_similarity)
    settings = settings.with_overrides(
        top_k=top_k, min_retrieval_similarity=min_similarity
    )

    if reset:
        st.session_state["session"] = agent.new_session()
        st.session_state["messages"] = []
        st.session_state.pop("pending_query", None)
        st.toast("Started a new conversation.")
        st.rerun()

    if "session" not in st.session_state:
        st.session_state["session"] = agent.new_session()
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    session = st.session_state["session"]

    header_left, header_right = st.columns([3, 1])
    with header_left:
        st.caption(
            f"Session `{session.session_id}` · model `{settings.chat_model}` · "
            f"threshold `{min_similarity:.2f}` · top-k `{top_k}`"
        )
    with header_right:
        if session.escalated:
            ticket = (session.handoff or {}).get("ticket_id", "open")
            st.caption(f"🎫 `{ticket}`")

    if not st.session_state["messages"]:
        st.info(
            "Ask a support question, or use an example query in the sidebar. "
            "Each answer shows the detected persona, retrieval confidence, and sources."
        )

    for index, entry in enumerate(st.session_state["messages"]):
        with st.chat_message("user", avatar="🧑‍💻"):
            st.markdown(entry["user"])
        with st.chat_message("assistant", avatar="🎧"):
            reply: AgentReply = entry["reply"]
            render_badges(reply)
            st.markdown(reply.message)
            render_escalation(reply, index)
            render_sources(reply)
            if debug:
                render_generation(reply)
            render_feedback(entry, index, settings)

    pending = st.session_state.pop("pending_query", None)
    prompt = st.chat_input("Describe the issue, include error text, or ask a policy question…")
    prompt = prompt or pending
    if prompt:
        forced = None if persona_mode == "Auto-detect" else Persona.from_label(persona_mode)
        with st.chat_message("user", avatar="🧑‍💻"):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar="🎧"):
            with st.status("Working through the support pipeline…", expanded=True) as status:
                status.write("1/4 · Detecting customer persona and sentiment")
                try:
                    reply = agent.respond(session, prompt, forced_persona=forced)
                    status.write("2/4 · Retrieving knowledge-base evidence")
                    status.write("3/4 · Generating persona-adapted, grounded response")
                    if reply.escalation.escalate:
                        status.update(
                            label="Escalated to a human specialist",
                            state="error",
                            expanded=False,
                        )
                    else:
                        status.update(
                            label="Answered from the knowledge base",
                            state="complete",
                            expanded=False,
                        )
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Agent turn failed")
                    status.update(label="Turn failed", state="error", expanded=True)
                    st.error(f"Something went wrong: {exc}")
                    st.stop()
            st.session_state["messages"].append({"user": prompt, "reply": reply})
            st.rerun()

    st.caption(
        "Responses are generated only from the NimbusDesk knowledge base. "
        "No refunds, account changes, or legal commitments are made in chat."
    )


if __name__ == "__main__":
    main()
