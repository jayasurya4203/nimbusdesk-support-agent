#!/usr/bin/env python3
"""Interactive command-line support agent.

Examples:
    python cli.py
    python cli.py --persona frustrated
    python cli.py --query "Bearer token returns 401" --json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from src.agent import SupportAgent
from src.config import ConfigurationError, Settings
from src.models import AgentReply, Persona

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

_COLORS = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
}


def _supports_color() -> bool:
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def paint(text: str, color: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{_COLORS[color]}m{text}\033[0m"


PERSONA_CHOICES = {
    "auto": None,
    "technical": Persona.TECHNICAL,
    "tech": Persona.TECHNICAL,
    "frustrated": Persona.FRUSTRATED,
    "executive": Persona.EXECUTIVE,
    "exec": Persona.EXECUTIVE,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persona-adaptive NimbusDesk support agent")
    parser.add_argument(
        "--persona",
        choices=sorted(PERSONA_CHOICES),
        default="auto",
        help="Force a persona instead of auto-detecting (default: auto)",
    )
    parser.add_argument("--query", help="Run one query non-interactively and exit")
    parser.add_argument(
        "--json", action="store_true", help="Print the full reply object as JSON"
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="Rebuild the vector index before starting"
    )
    return parser.parse_args()


def build_agent(settings: Settings, rebuild: bool) -> SupportAgent:
    if rebuild:
        from src.embeddings import GeminiEmbedder
        from src.rag import KnowledgeBase

        print(paint("Rebuilding knowledge base index…", "yellow"))
        embedder = GeminiEmbedder(
            api_key=settings.require_api_key(),
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
            max_retries=settings.max_retries,
            base_delay_s=settings.retry_base_delay_s,
            inputs_per_minute=settings.embedding_inputs_per_minute,
        )
        KnowledgeBase(settings, embedder).build(progress=_progress)
        print()

    return SupportAgent.production(
        settings,
        build_index_if_missing=True,
        progress=_progress,
    )


def _progress(done: int, total: int, label: str) -> None:
    print(f"\r  {label:<32}", end="", flush=True)


def print_reply(reply: AgentReply, show_sources: bool = True) -> None:
    persona = reply.persona
    print()
    print(
        paint("  persona   ", "dim")
        + paint(persona.persona.value, "magenta")
        + paint(
            f"  ({persona.confidence:.0%} confidence · {persona.source}"
            f" · frustration {persona.frustration_score:.2f})",
            "dim",
        )
    )
    print(
        paint("  retrieval ", "dim")
        + f"{reply.retrieval_confidence:.2f}"
        + paint("   response ", "dim")
        + f"{reply.response_confidence:.2f}"
        + paint(
            "   (scores are 0-1; retrieval is the fused relevance of the best chunk)", "dim"
        )
    )
    if show_sources and reply.sources:
        print(paint("  sources", "dim"))
        for index, chunk in enumerate(reply.sources, start=1):
            location = f"p. {chunk.page}" if chunk.page else chunk.section
            print(
                paint(f"    [{index}] ", "dim")
                + f"{chunk.source} · {location} · score {chunk.score:.2f}"
            )

    if reply.escalation.escalate:
        ticket = (reply.handoff or {}).get("ticket_id", "pending")
        print(paint(f"  ESCALATED → human handoff {ticket}", "red"))
        for reason in reply.escalation.reasons:
            print(paint(f"    - {reason.label}: {reason.detail}", "yellow"))
        if reply.handoff_paths:
            print(paint(f"    handoff saved: {reply.handoff_paths['json']}", "dim"))
    else:
        print(paint("  status    resolved from knowledge base", "green"))

    print()
    print(reply.message)
    if reply.timings_ms:
        timings = " · ".join(f"{key.removesuffix('_ms')} {value}ms" for key, value in reply.timings_ms.items())
        print()
        print(paint(f"  {timings}", "dim"))
    print()


def print_help() -> None:
    print(
        """
Commands
  /help                 Show this help
  /persona <name>       Force persona: auto | technical | frustrated | executive
  /sources              Show retrieved sources for the last answer
  /handoff              Print the last handoff JSON
  /reset                Start a new conversation (new session and ticket)
  /stats                Show knowledge-base statistics
  /quit                 Exit
""".rstrip()
    )


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.load()

    if not settings.has_api_key:
        print(paint("GEMINI_API_KEY is not set.", "red"))
        print(
            "Copy .env.example to .env, add a key from https://aistudio.google.com/apikey, "
            "then run again."
        )
        return 2

    try:
        agent = build_agent(settings, args.rebuild)
    except (ConfigurationError, FileNotFoundError, RuntimeError) as exc:
        print(paint(f"Startup failed: {exc}", "red"))
        return 1

    forced = PERSONA_CHOICES[args.persona]
    session = agent.new_session()

    if args.query:
        reply = agent.respond(session, args.query, forced_persona=forced)
        if args.json:
            print(json.dumps(reply.to_dict(), indent=2, ensure_ascii=False, default=str))
        else:
            print(f"\n{paint('you ›', 'cyan')} {args.query}")
            print_reply(reply)
        return 0

    stats = agent.kb.stats()
    print()
    print(paint("NimbusDesk persona-adaptive support agent", "bold"))
    print(
        paint(
            f"  model {settings.chat_model} · embeddings {stats['embedding_model']} "
            f"· {stats['chunk_count']} chunks from {stats['document_count']} documents",
            "dim",
        )
    )
    print(paint(f"  session {session.session_id} · persona {args.persona}", "dim"))
    print(paint("  Type /help for commands, /quit to exit.", "dim"))
    print()

    last_reply: AgentReply | None = None
    while True:
        try:
            line = input(paint("you › ", "cyan")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue

        if line.startswith("/"):
            command, _, argument = line[1:].partition(" ")
            command = command.lower()
            if command in {"quit", "exit"}:
                break
            if command == "help":
                print_help()
            elif command == "persona":
                key = argument.strip().lower() or "auto"
                if key not in PERSONA_CHOICES:
                    print(paint("  Use: /persona auto|technical|frustrated|executive", "yellow"))
                else:
                    forced = PERSONA_CHOICES[key]
                    print(paint(f"  Persona mode: {key}", "green"))
            elif command == "sources":
                if last_reply and last_reply.sources:
                    for index, chunk in enumerate(last_reply.sources, start=1):
                        location = f"p. {chunk.page}" if chunk.page else chunk.section
                        print(f"\n[{index}] {chunk.source} · {location} · {chunk.score:.3f}")
                        print(paint(chunk.text[:700], "dim"))
                else:
                    print(paint("  No sources yet.", "yellow"))
            elif command == "handoff":
                if last_reply and last_reply.handoff:
                    print(json.dumps(last_reply.handoff, indent=2, ensure_ascii=False))
                else:
                    print(paint("  No handoff in this session.", "yellow"))
            elif command == "reset":
                session = agent.new_session()
                last_reply = None
                print(paint(f"  New session {session.session_id}", "green"))
            elif command == "stats":
                print(json.dumps(agent.kb.stats(), indent=2, ensure_ascii=False))
            else:
                print(paint(f"  Unknown command /{command}. Try /help.", "yellow"))
            continue

        try:
            revision = agent.respond(session, line, forced_persona=forced)
        except Exception as exc:  # noqa: BLE001 - keep the REPL alive
            print(paint(f"  Error: {exc}", "red"))
            continue
        last_reply = revision
        print_reply(revision)

    if session.handoff_paths:
        print(paint(f"Handoff files: {session.handoff_paths}", "dim"))
    print(paint("Goodbye.", "dim"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
