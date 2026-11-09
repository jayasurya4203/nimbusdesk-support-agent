#!/usr/bin/env python3
"""Scripted end-to-end demo across all three personas plus escalation paths.

    python scripts/demo.py

The script calls the real agent (Gemini + the indexed knowledge base). It writes
a Markdown transcript to ``demo_output/demo_transcript.md`` for the screen
recording and prints a pass/fail summary for the expected behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.agent import SupportAgent  # noqa: E402
from src.config import Settings  # noqa: E402
from src.models import AgentReply, Persona  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CASES: list[dict] = [
    {
        "title": "Frustrated user: browser cache / page not loading",
        "messages": [
            "Where is the guide to clear cookies? It's been an hour and nothing is loading "
            "on your interface!"
        ],
        "expect_persona": Persona.FRUSTRATED,
        "expect_escalation": False,
        "show": "Empathetic, simple, action-oriented answer from the browser guide.",
    },
    {
        "title": "Technical expert: bearer token headers",
        "messages": [
            "What are the header parameter requirements for your bearer token auth "
            "implementation? Include the exact error codes for an invalid key."
        ],
        "expect_persona": Persona.TECHNICAL,
        "expect_escalation": False,
        "show": "Exact headers, 401 error codes, and verification steps.",
    },
    {
        "title": "Business executive: uptime commitment and incident contacts",
        "messages": [
            "Our operational uptime is decreasing. What uptime commitment do we have and "
            "who should we contact during an incident?"
        ],
        "expect_persona": Persona.EXECUTIVE,
        "expect_escalation": False,
        "show": "Bottom line, documented uptime commitment, and a clear next step.",
    },
    {
        "title": "Technical expert: database connector internal errors",
        "messages": [
            "I'm experiencing an issue with your database integration that's causing internal "
            "errors on ticket pages. We use PostgreSQL with a lookup table."
        ],
        "expect_persona": Persona.TECHNICAL,
        "expect_escalation": False,
        "show": "Root-cause analysis and step-by-step connector diagnostics.",
    },
    {
        "title": "Frustrated user: duplicate charge and refund demand",
        "messages": [
            "My billing statement has unexpected duplicate charges. I demand an immediate "
            "refund!"
        ],
        "expect_persona": Persona.FRUSTRATED,
        "expect_escalation": True,
        "show": "Sensitive billing request escalates with a structured handoff.",
    },
    {
        "title": "Business executive: export capacity and business risk",
        "messages": [
            "How long does it take to export 500,000 tickets, and what's the business risk "
            "if the export fails?"
        ],
        "expect_persona": Persona.EXECUTIVE,
        "expect_escalation": False,
        "show": "Business-level answer grounded in the export guide.",
    },
    {
        "title": "Frustrated user: lockout and expired reset link (PDF source)",
        "messages": [
            "I'm locked out after five failed login attempts and the password reset link says "
            "it's no longer valid. This is the third time!"
        ],
        "expect_persona": Persona.FRUSTRATED,
        "expect_escalation": False,
        "show": "Answer cites the password reset PDF with page metadata.",
    },
    {
        "title": "Out-of-domain question: low retrieval confidence",
        "messages": [
            "Can you ship a physical welcome kit to our Antarctic research station, and what "
            "import tax applies to the branded mugs?"
        ],
        "expect_persona": None,
        "expect_escalation": True,
        "show": "No documentation match → escalate instead of hallucinating.",
    },
    {
        "title": "Multi-turn frustration: repeated unsuccessful attempts",
        "messages": [
            "Our whole team is locked out of SSO and nobody can log in!",
            "I already cleared cookies and tried incognito, and it still doesn't work. "
            "This is unacceptable.",
        ],
        "expect_persona": Persona.FRUSTRATED,
        "expect_escalation": True,
        "show": "Persistent dissatisfaction across turns triggers a human handoff.",
    },
]


def _sources_markdown(reply: AgentReply) -> str:
    if not reply.sources:
        return "_none_"
    lines = []
    for chunk in reply.sources:
        location = f"page {chunk.page}" if chunk.page else chunk.section
        lines.append(
            f"- `{chunk.source}` · {location} · score {chunk.score:.3f} "
            f"(dense {chunk.dense_score:.3f}, lexical {chunk.lexical_score:.3f})"
        )
    return "\n".join(lines)


def run_case(agent: SupportAgent, case: dict) -> dict:
    session = agent.new_session()
    replies = [agent.respond(session, message) for message in case["messages"]]
    final = replies[-1]
    persona_ok = (
        case["expect_persona"] is None
        or final.persona.persona == case["expect_persona"]
    )
    escalation_ok = final.escalation.escalate == case["expect_escalation"]
    return {
        "case": case,
        "replies": replies,
        "session": session,
        "persona_ok": persona_ok,
        "escalation_ok": escalation_ok,
        "passed": persona_ok and escalation_ok,
    }


def write_transcript(results: list[dict], settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# NimbusDesk persona-adaptive support agent — demo transcript",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Chat model: `{settings.chat_model}` · Embeddings: `{settings.embedding_model}` "
        f"({settings.embedding_dimensions} dims)",
        "",
    ]
    for number, result in enumerate(results, start=1):
        case = result["case"]
        lines += [f"## Case {number} — {case['title']}", "", f"_{case['show']}_", ""]
        for turn_index, message in enumerate(case["messages"]):
            reply = result["replies"][turn_index]
            lines += [f"**User:** {message}", ""]
            lines += [
                f"**Detected persona:** {reply.persona.persona.value} "
                f"({reply.persona.confidence:.0%}, {reply.persona.source}) · "
                f"frustration {reply.persona.frustration_score:.2f}",
                "",
                f"**Retrieval confidence:** {reply.retrieval_confidence:.3f} · "
                f"**Response confidence:** {reply.response_confidence:.3f}",
                "",
                "**Retrieved sources:**",
                _sources_markdown(reply),
                "",
                f"**Escalation:** {'YES' if reply.escalation.escalate else 'no'}",
                "",
            ]
            if reply.escalation.reasons:
                lines += [
                    f"- {reason.label} (`{reason.code}`): {reason.detail}"
                    for reason in reply.escalation.reasons
                ]
                lines.append("")
            lines += ["**Assistant:**", "", reply.message, ""]
            if reply.handoff:
                lines += [
                    "<details><summary>Human handoff JSON</summary>",
                    "",
                    "```json",
                    json.dumps(reply.handoff, indent=2, ensure_ascii=False),
                    "```",
                    "",
                    "</details>",
                    "",
                ]
        lines += ["---", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scripted demo scenarios")
    parser.add_argument("--no-save", action="store_true", help="Do not write the transcript file")
    args = parser.parse_args()

    settings = Settings.load()
    if not settings.has_api_key:
        print("GEMINI_API_KEY is not set. Add it to .env first.")
        return 2

    def progress(done: int, total: int, label: str) -> None:
        print(f"\r  {label:<40}", end="", flush=True)

    print("Loading agent and knowledge base...")
    agent = SupportAgent.production(settings, build_index_if_missing=True, progress=progress)
    print()

    results: list[dict] = []
    for number, case in enumerate(CASES, start=1):
        print(f"\n[{number}/{len(CASES)}] {case['title']}")
        result = run_case(agent, case)
        results.append(result)
        final = result["replies"][-1]
        expected = case["expect_persona"].value if case["expect_persona"] else "any"
        print(
            f"  persona   {final.persona.persona.value} "
            f"({final.persona.confidence:.0%}) [expected: {expected}]"
        )
        print(
            f"  sources   {', '.join(sorted({s.source for s in final.sources})) or 'none'}"
        )
        print(
            f"  escalated {final.escalation.escalate} "
            f"[expected: {case['expect_escalation']}]"
            + (
                f" -> {(final.handoff or {}).get('ticket_id')}"
                if final.escalation.escalate
                else ""
            )
        )
        print(f"  result    {'PASS' if result['passed'] else 'CHECK'}")
        print(f"  reply     {final.message[:180].replace(chr(10), ' ')}...")

    if not args.no_save:
        path = PROJECT_ROOT / "demo_output" / "demo_transcript.md"
        write_transcript(results, settings, path)
        print(f"\nTranscript written to {path}")

    passed = sum(1 for result in results if result["passed"])
    print(f"\n{passed}/{len(results)} cases matched their expected persona and escalation behavior.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
