"""Append-only feedback log (JSON Lines) for the Streamlit UI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def record_feedback(
    path: Path,
    *,
    session_id: str,
    persona: str,
    rating: str,
    message: str,
    response_excerpt: str,
    sources: list[str],
    comment: str = "",
    escalated: bool = False,
) -> dict[str, Any]:
    if rating not in {"up", "down"}:
        raise ValueError("rating must be 'up' or 'down'")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": session_id,
        "persona": persona,
        "rating": rating,
        "message": message[:1000],
        "response_excerpt": response_excerpt[:1000],
        "sources": sources,
        "comment": comment[:1000],
        "escalated": escalated,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry
